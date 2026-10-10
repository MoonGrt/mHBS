#include "Vtb_fast.h"
#include "verilated.h"
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static std::vector<std::string> lines(const std::string &path) {
    std::ifstream f(path);if(!f)throw std::runtime_error("Cannot read "+path);
    std::vector<std::string> r;std::string s;while(f>>s)r.push_back(s);return r;
}
static unsigned byte(const VlWide<8> &value,unsigned i) {return (value[i/4]>>(8*(i%4)))&255;}
static void node(VlWide<8> &value,std::string hex) {
    while(hex.size()<64)hex="0"+hex;
    for(unsigned i=0;i<8;i++)value[i]=std::stoul(hex.substr(64-8*(i+1),8),nullptr,16);
}
int main(int argc,char **argv) {
 try {
    VerilatedContext context;context.commandArgs(argc,argv);
    std::string path;
    for(int i=1;i<argc;i++)if(std::string(argv[i]).rfind("+VECTOR=",0)==0)path=argv[i]+8;
    if(path.empty())throw std::runtime_error("VECTOR is required");
    auto meta=lines(path+"/meta.mem"),cfg=lines(path+"/job.mem"),msg=lines(path+"/message.mem");
    auto expected=lines(path+"/expected.mem"),nodes=lines(path+"/nodes.mem");
    auto number=[](const std::string &s){return std::stoull(s,nullptr,16);};
    const uint64_t output_size=number(meta[0]),expected_hashes=number(meta[1]),expected_perms=number(meta[2]);
    const unsigned op=number(cfg[7]),message_size=op?number(cfg[8]):0,verify_nodes=number(meta[3]);
    Vtb_fast dut{&context};uint64_t ticks=0,hashes=0,perms=0,cursor=0,observed_cycles=0;
    unsigned sent=0,accepted=0;
    auto tick=[&](bool observe) {
        dut.clk=0;dut.eval();
        if(observe) {
            if(dut.execution_reset){hashes=0;perms=0;observed_cycles=0;}
            else {observed_cycles+=dut.execution_active;hashes+=dut.hash_event+dut.batch_event;perms+=dut.permutation_event+dut.batch_event;}
            if(dut.message_valid&&dut.message_ready)sent+=8;
            if(dut.verify_valid&&dut.verify_ready)accepted++;
            if(dut.out_valid)for(unsigned i=0;i<dut.out_bytes;i++) {
                if(cursor>=output_size || byte(dut.out_data,i)!=number(expected[cursor]))
                    throw std::runtime_error("Output byte mismatch at "+std::to_string(cursor));
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
                cursor++;
            }
        }
        if(cursor!=output_size)throw std::runtime_error("Signature cache length mismatch");
    }
    std::cout<<"STATEFUL_PASS P"<<dut.configuration_pipeline<<"U"<<dut.configuration_unroll
             <<" op="<<op<<" cycles="<<cycles<<" total="<<total
             <<" hashes="<<hashes<<" permutations="<<perms<<" tamper=0"
             <<" seconds="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<std::endl;
    dut.final();return 0;
 } catch(const std::exception &e) {std::cerr<<e.what()<<std::endl;return 1;}
}
