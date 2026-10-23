#include "Vtb_fast.h"
#include "verilated.h"
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <map>
#include <array>

static std::vector<std::string> lines(const std::string &path) {
    std::ifstream f(path);if(!f)throw std::runtime_error("Cannot read "+path);
    std::vector<std::string> r;std::string s;while(f>>s)r.push_back(s);return r;
}
static unsigned byte(const VlWide<8> &value,unsigned i) {return (value[i/4]>>(8*(i%4)))&255;}
static void node(VlWide<8> &value,std::string hex) {
    while(hex.size()<64)hex="0"+hex;
    for(unsigned i=0;i<8;i++)value[i]=std::stoul(hex.substr(64-8*(i+1),8),nullptr,16);
}
static void dump_bytes(const std::string &path,const std::vector<uint8_t> &data) {
    if(path.empty())return;
    std::ofstream stream(path,std::ios::binary);
    if(!stream)throw std::runtime_error("Cannot write "+path);
    stream.write(reinterpret_cast<const char *>(data.data()),data.size());
    if(!stream)throw std::runtime_error("Cannot finish writing "+path);
}
int main(int argc,char **argv) {
 try {
    VerilatedContext context;context.commandArgs(argc,argv);
    std::string path,output_path,cache_path,histogram_path;
    for(int i=1;i<argc;i++) {
        const std::string argument=argv[i];
        if(argument.rfind("+VECTOR=",0)==0)path=argument.substr(8);
        if(argument.rfind("+OUTPUT_BIN=",0)==0)output_path=argument.substr(12);
        if(argument.rfind("+CACHE_BIN=",0)==0)cache_path=argument.substr(11);
        if(argument.rfind("+HISTOGRAM=",0)==0)histogram_path=argument.substr(11);
    }
    if(path.empty())throw std::runtime_error("VECTOR is required");
    auto meta=lines(path+"/meta.mem"),cfg=lines(path+"/job.mem"),msg=lines(path+"/message.mem");
    auto expected=lines(path+"/expected.mem"),nodes=lines(path+"/nodes.mem");
    auto number=[](const std::string &s){return std::stoull(s,nullptr,16);};
    const uint64_t output_size=number(meta[0]),expected_hashes=number(meta[1]),logical_perms=number(meta[2]);
    const unsigned op=number(cfg[7]),message_size=op?number(cfg[8]):0,verify_nodes=number(meta[3]);
    // Vector meta retains the algorithm's logical padded-block count. SHA2
    // SLH address hashes reuse one raw PK.seed chaining value per reset/job;
    // compression events count actual lane work, including its one cold fill.
    const auto descriptors=lines(path+"/descriptor.mem");
    const uint64_t profile=number(descriptors.at(1));
    uint64_t expected_perms=logical_perms;
    if((profile&32) && ((profile&31)==0 || (profile&31)==4)) {
        const uint64_t mgf_hashes=(profile&31)==0 ? 2 : 1;
        const uint64_t message_hashes=op==0 ? 0 : 1+mgf_hashes+(op==1 ? 2 : 0);
        if(expected_hashes<message_hashes)throw std::runtime_error("Invalid SLH vector hash count");
        const uint64_t address_hashes=expected_hashes-message_hashes;
        if(address_hashes && logical_perms<address_hashes)
            throw std::runtime_error("Invalid SLH vector compression count");
        expected_perms=logical_perms-address_hashes+(address_hashes ? 1 : 0);
    }
    Vtb_fast dut{&context};uint64_t ticks=0,hashes=0,perms=0,cursor=0,observed_cycles=0;
    std::vector<uint8_t> output_bytes,cache_bytes;
    uint64_t prof_hash=0,prof_other=0,prof_round=0,prof_ff=0,prof_internal=0;
    std::map<uint64_t,uint64_t> joint_hist;
    std::map<std::string,uint64_t> categories;
    std::array<uint64_t,256> executor_hist{},control_fetch{},control_issue{},control_wait{},accepted_control{};
    std::array<uint64_t,256> sequencer_hist{};
    std::array<uint64_t,8> lane_state_hist{};
    std::array<uint64_t,16> macro_count{},recipe_nonhash{},recipe_hash{},recipe_requests{},template_nonhash{};
    bool hash_template_active=false,recipe_active=false;
    unsigned current_recipe=0;
    uint64_t templates=0,template_nonhash_total=0,recipe_nonhash_total=0,hash_template_cycles=0;
    unsigned sent=0,accepted=0;
    auto tick=[&](bool observe) {
        dut.clk=0;dut.eval();
        if(observe) {
            if(dut.execution_reset){hashes=0;perms=0;observed_cycles=0;prof_hash=0;prof_other=0;prof_round=0;prof_ff=0;prof_internal=0;}
            else {
                observed_cycles+=dut.profile_active;hashes+=dut.hash_event+dut.batch_event;perms+=dut.permutation_event+dut.batch_event;
                if(dut.profile_active) {
                    prof_hash+=dut.profile_hash;prof_other+=!dut.profile_hash;
                    prof_round+=dut.profile_round;prof_ff+=dut.profile_feedforward;
                    prof_internal+=dut.profile_internal_transfer;
                    const unsigned ex=dut.profile_executor_state,seq=dut.profile_sequencer_state;
                    const unsigned op=dut.profile_control_op,kind=dut.profile_token_kind;
                    const unsigned ls=dut.profile_lane_state,lp=dut.profile_lane_phase;
                    if(dut.command_event) {
                        macro_count[dut.command_opcode]++;
                        if(dut.command_opcode==1) {
                            if(hash_template_active)throw std::runtime_error("Overlapping HASH templates");
                            hash_template_active=true;templates++;
                        }
                    }
                    if(dut.control_event)accepted_control[op]++;
                    if(dut.recipe_request_event) {
                        if(recipe_active)throw std::runtime_error("Overlapping scalar recipes");
                        recipe_active=true;current_recipe=dut.profile_recipe_shape;recipe_requests[current_recipe]++;
                    }
                    if(hash_template_active)hash_template_cycles++;
                    if(recipe_active) {
                        if(dut.profile_hash)recipe_hash[current_recipe]++;
                        else {recipe_nonhash[current_recipe]++;recipe_nonhash_total++;}
                    }
                    if(!dut.profile_hash) {
                        const uint64_t key=uint64_t(ex)|(uint64_t(seq)<<8)|(uint64_t(op)<<16)|
                            (uint64_t(kind)<<21)|(uint64_t(ls)<<23)|(uint64_t(lp)<<31)|
                            (uint64_t(hash_template_active)<<39)|(uint64_t(dut.profile_macro_op)<<40)|
                            (uint64_t(dut.profile_recipe_shape)<<44);
                        joint_hist[key]++;executor_hist[ex]++;sequencer_hist[seq]++;lane_state_hist[ls]++;
                        if(hash_template_active) {
                            categories["hash_template_nonhash"]++;template_nonhash_total++;
                            template_nonhash[dut.profile_recipe_shape]++;
                        } else if(dut.profile_seq_fetch && dut.profile_fetch_kind==3 && dut.profile_fetch_op>=1 && dut.profile_fetch_op<=15) {
                            categories["software_control_fetch"]++;control_fetch[dut.profile_fetch_op]++;
                        } else if(dut.profile_seq_load && kind==3 && op>=1 && op<=15) {
                            categories["software_control_issue"]++;control_issue[op]++;
                        } else if(dut.profile_seq_control_wait) {
                            categories["software_control_wait"]++;control_wait[op]++;
                        } else if((dut.profile_seq_fetch && dut.profile_fetch_kind==2)||(dut.profile_seq_load && kind==2)) {
                            categories["software_loop_fetch_issue"]++;
                        } else if(dut.profile_is_transform)categories["transform_execution"]++;
                        else if(dut.profile_is_output)categories["output_execution"]++;
                        else if(dut.profile_is_lifecycle)categories["job_message_lifecycle"]++;
                        else categories["other_template_fetch_issue_retire"]++;
                    }
                    if(dut.profile_recipe_complete) {
                        if(!recipe_active)throw std::runtime_error("Recipe response without request");
                        recipe_active=false;
                    }
                    if(hash_template_active && dut.profile_template_complete)hash_template_active=false;

                }
            }
            if(dut.message_valid&&dut.message_ready)sent+=8;
            if(dut.verify_valid&&dut.verify_ready)accepted++;
            if(dut.out_valid)for(unsigned i=0;i<dut.out_bytes;i++) {
                if(cursor>=output_size || byte(dut.out_data,i)!=number(expected[cursor]))
                    throw std::runtime_error("Output byte mismatch at "+std::to_string(cursor));
                if(!output_path.empty())output_bytes.push_back(byte(dut.out_data,i));
                cursor++;
            }
        }
        context.timeInc(5);dut.clk=1;dut.eval();context.timeInc(5);ticks++;
    };
    dut.rst=1;dut.message_valid=0;dut.verify_valid=0;dut.signature_read_enable=0;
    for(unsigned i=0;i<5;i++)tick(false);dut.rst=0;
    auto start=std::chrono::steady_clock::now();
    while(!dut.done&&!dut.error) {
        dut.message_valid=sent<message_size;
        dut.message_data=0;
        if(dut.message_valid)for(unsigned i=0;i<8&&sent+i<message_size;i++)
            dut.message_data|=number(msg[sent+i])<<(8*i);
        dut.verify_valid=op==2&&accepted<verify_nodes;
        if(dut.verify_valid)node(dut.verify_data,nodes[accepted]);
        tick(true);
        if(ticks>100000000000ULL)throw std::runtime_error("Timeout");
        if(ticks%1000000000ULL==0)std::cout<<"RTL_PROGRESS ticks="<<ticks<<" hashes="<<hashes<<std::endl;
    }
    if(dut.error)throw std::runtime_error("RTL error "+std::to_string(dut.error_code));
    if(cursor!=output_size || hashes!=expected_hashes || perms!=expected_perms
       || (dut.debug_stats && (dut.hash_count!=hashes || dut.permutation_count!=perms))
       || (!dut.debug_stats && !dut.statistics_zero))
        throw std::runtime_error("Length or statistics mismatch: "+std::to_string(cursor)+" "+std::to_string(hashes)+" "+std::to_string(perms));
    if(op==2&&(!dut.verify_pass || accepted!=verify_nodes))throw std::runtime_error("Verify mismatch");
    const uint64_t cycles=dut.debug_stats ? dut.execution_cycles : observed_cycles,total=ticks-5;
    if(op==1) {
        if(!dut.signature_complete||dut.signature_error||dut.signature_length!=output_size)
            throw std::runtime_error("Signature metadata mismatch");
        cursor=0;unsigned count=dut.signature_nodes;
        for(unsigned i=0;i<count;i++) {
            dut.signature_read_enable=1;dut.signature_read_address=i;tick(false);
            if(!dut.signature_read_valid)throw std::runtime_error("Signature read not valid");
            for(unsigned b=0;b<dut.signature_read_bytes;b++) {
                if(cursor>=output_size||byte(dut.signature_read_data,b)!=number(expected[cursor]))
                    throw std::runtime_error("Signature cache byte mismatch");
                if(!cache_path.empty())cache_bytes.push_back(byte(dut.signature_read_data,b));
                cursor++;
            }
        }
        if(cursor!=output_size)throw std::runtime_error("Signature cache length mismatch");
    }
    if(!cache_path.empty()&&op!=1)throw std::runtime_error("CACHE_BIN requires Sign");
    dump_bytes(output_path,output_bytes);
    dump_bytes(cache_path,cache_bytes);
    std::cout<<"STATEFUL_PASS P"<<dut.configuration_pipeline<<"U"<<dut.configuration_unroll
             <<" op="<<op<<" cycles="<<cycles<<" total="<<total
             <<" hashes="<<hashes<<" permutations="<<perms<<" tamper=0"
             <<" logical_permutations="<<logical_perms
             <<" seconds="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<std::endl;
    std::cout<<"CLOCK_COUNTER_CHECK observed="<<observed_cycles<<" hash="<<prof_hash<<" other="<<prof_other
             <<" round="<<prof_round<<" ff="<<prof_ff<<" production_cycles="<<cycles<<std::endl;
    if(prof_hash+prof_other!=cycles || observed_cycles!=cycles || prof_round+prof_ff!=prof_hash)
        throw std::runtime_error("Cycle partition differs from production counter");
    std::cout<<"CLOCK_BREAKDOWN total="<<cycles<<" hash="<<prof_hash<<" transfer=0 remaining="<<prof_other
             <<" rounds="<<prof_round<<" feedforward="<<prof_ff<<" internal_handoff_overlap_diagnostic="<<prof_internal<<std::endl;
    uint64_t histogram_total=0,category_total=0;
    for(const auto &x:joint_hist)histogram_total+=x.second;
    for(const auto &x:categories)category_total+=x.second;
    if(histogram_total!=prof_other || category_total!=prof_other || hash_template_active || recipe_active)
        throw std::runtime_error("Remaining attribution partition mismatch");
    if(histogram_path.empty())throw std::runtime_error("HISTOGRAM output required");
    std::ofstream h(histogram_path);if(!h)throw std::runtime_error("Cannot write histogram");
    h<<"{\n\"total\":"<<cycles<<",\n\"hash\":"<<prof_hash<<",\n\"remaining\":"<<prof_other
     <<",\n\"hash_template_count\":"<<templates<<",\n\"hash_template_cycles\":"<<hash_template_cycles
     <<",\n\"hash_template_nonhash\":"<<template_nonhash_total<<",\n\"recipe_nonhash\":"<<recipe_nonhash_total;
    h<<",\n\"categories\":{";bool first=true;
    for(const auto &x:categories){if(!first)h<<",";first=false;h<<"\""<<x.first<<"\":"<<x.second;}h<<"}";
    h<<",\n\"executor_histogram\":[";for(unsigned i=0;i<256;i++){if(i)h<<",";h<<executor_hist[i];}h<<"]";
    h<<",\n\"sequencer_histogram\":[";for(unsigned i=0;i<256;i++){if(i)h<<",";h<<sequencer_hist[i];}h<<"]";
    h<<",\n\"lane_state_histogram\":[";for(unsigned i=0;i<8;i++){if(i)h<<",";h<<lane_state_hist[i];}h<<"]";
    h<<",\n\"control_op_histogram\":[";
    for(unsigned i=0;i<32;i++){if(i)h<<",";h<<"{\"opcode\":"<<i<<",\"accepted\":"<<accepted_control[i]<<",\"fetch\":"<<control_fetch[i]<<",\"issue\":"<<control_issue[i]<<",\"wait\":"<<control_wait[i]<<"}";}h<<"]";
    h<<",\n\"recipe_histogram\":[";
    for(unsigned i=0;i<16;i++){if(i)h<<",";h<<"{\"shape\":"<<i<<",\"requests\":"<<recipe_requests[i]<<",\"hash\":"<<recipe_hash[i]<<",\"nonhash\":"<<recipe_nonhash[i]<<",\"template_nonhash_at_current_shape\":"<<template_nonhash[i]<<"}";}h<<"]";
    h<<",\n\"macro_histogram\":[";for(unsigned i=0;i<16;i++){if(i)h<<",";h<<macro_count[i];}h<<"]";
    h<<",\n\"joint_histogram\":[";first=true;
    for(const auto &x:joint_hist){if(!first)h<<",";first=false;const auto k=x.first;
        h<<"{\"executor\":"<<(k&255)<<",\"sequencer\":"<<((k>>8)&255)<<",\"control_opcode\":"<<((k>>16)&31)
         <<",\"token_kind\":"<<((k>>21)&3)<<",\"lane_state\":"<<((k>>23)&255)<<",\"lane_phase\":"<<((k>>31)&255)
         <<",\"hash_template_active\":"<<((k>>39)&1)<<",\"macro\":"<<((k>>40)&15)
         <<",\"recipe_shape\":"<<((k>>44)&15)<<",\"cycles\":"<<x.second<<"}";}h<<"]\n}\n";
    h.close();std::cout<<"ATTRIBUTION_PASS remaining="<<histogram_total<<" templates="<<templates
      <<" template_nonhash="<<template_nonhash_total<<" recipe_nonhash="<<recipe_nonhash_total<<std::endl;
    dut.final();return 0;
 } catch(const std::exception &e) {std::cerr<<e.what()<<std::endl;return 1;}
}
