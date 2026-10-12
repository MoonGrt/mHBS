#!/usr/bin/env python3
"""Compare the actual old/new scalar source functions over every control field."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from apply_source_bank import OLD, NEW

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
BEFORE = ROOT / 'rtl/hash/recipe.sv'
AFTER = WORK / 'recipe.sv'

def extract(text, name):
    start = text.index('            function automatic [63:0] ' + name + '(')
    end = text.index('            endfunction', start) + len('            endfunction')
    return text[start:end]

def main():
    original = BEFORE.read_text()
    updated = AFTER.read_text()
    old_source = extract(original, 'source_word')
    new_source = extract(updated, 'source_word')
    stripped_new = new_source.replace('                reg [255:0] selected_node;\n', '').replace(NEW, OLD)
    assert stripped_new == old_source, 'the selector control must be unchanged'
    helpers = extract(original, 'node_word') + '\n' + extract(original, 'message_word')
    functions = helpers + '\n' + old_source.replace('source_word', 'old_source_word') + '\n' + new_source.replace('source_word', 'new_source_word')
    tb = '''`timescale 1ns/1ps
module tb_source_bank;
    localparam [15:0] RECIPE_MASK = 16'hffff;
    localparam [3:0] MESSAGE_PRF=3, MESSAGE_DIGEST=4, ROOT_MESSAGE=6,
        PREFIX_MESSAGE=11, ADDRESS_LIST=12, PREFIX_LIST=13;
    logic [15:0] shapes;
    logic [2:0] node_words;
    logic [255:0] secret_prf,randomizer,public_seed,root,address,list_data0;
    logic [127:0] identifier;
    logic [31:0] leaf;
    logic [695:0] message_buffer;
    wire [703:0] padded_message = {8'd0,message_buffer};
    function automatic [31:0] be32(input [31:0] value);
        be32={value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
''' + functions + '''
    integer seed_i, shape_i, words_i, index_i, lms_i, word_i, cases=0;
    task random_inputs;
        for (word_i=0;word_i<8;word_i=word_i+1) begin
            secret_prf[word_i*32+:32]=$random;
            randomizer[word_i*32+:32]=$random;
            public_seed[word_i*32+:32]=$random;
            root[word_i*32+:32]=$random;
            address[word_i*32+:32]=$random;
            list_data0[word_i*32+:32]=$random;
        end
        for (word_i=0;word_i<21;word_i=word_i+1)
            message_buffer[word_i*32+:32]=$random;
        message_buffer[695:672]=$random;
        identifier={$random,$random,$random,$random};
        leaf=$random;
    endtask
    initial begin
        for(seed_i=0;seed_i<32;seed_i=seed_i+1) begin
            random_inputs();
            for(shape_i=0;shape_i<16;shape_i=shape_i+1) begin
                shapes=16'b1<<shape_i;
                for(words_i=0;words_i<8;words_i=words_i+1) begin
                    node_words=3'(words_i);
                    for(index_i=0;index_i<64;index_i=index_i+1)
                        for(lms_i=0;lms_i<2;lms_i=lms_i+1) begin
                            if(old_source_word(6'(index_i),1'(lms_i)) !==
                               new_source_word(6'(index_i),1'(lms_i)))
                                $fatal(1,"source mismatch shape=%0d words=%0d index=%0d lms=%0d",shape_i,words_i,index_i,lms_i);
                            cases=cases+1;
                        end
                end
            end
        end
        $display("PASS actual scalar source functions: %0d cases",cases);
        $finish;
    end
endmodule
'''
    (WORK/'tb_source_bank.sv').write_text(tb)
    command = ['verilator','--binary','--timing','-Wno-fatal','-O3','-j','2',
               '--top-module','tb_source_bank','--Mdir',str(WORK/'obj'),
               str(WORK/'tb_source_bank.sv')]
    with (WORK/'compile.log').open('w') as stream:
        subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
    result = subprocess.run([str(WORK/'obj/Vtb_source_bank')],text=True,
                            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (WORK/'run.log').write_text(result.stdout)
    result.check_returncode()
    summary = {'passed':True,'cases':524288,'shape_values':16,'node_words_values':8,
               'indices':64,'lms_only_values':2,'random_data_sets':32,
               'control_text_unchanged':True,
               'algebra':{'source_range':'0..7','node_sources':[1,2,3,4,6,7],
                          'source0':'literal unchanged','source5':'message_word unchanged',
                          'selected_index_ge4':'node_word returns 0 in both paths',
                          'wide_data_proof':'bank case selects the same 256-bit input; node_word then returns the same fixed slice for indices 0..3, else zero'},
               'original_recipe_sha256':hashlib.sha256(original.encode()).hexdigest(),
               'candidate_recipe_sha256':hashlib.sha256(updated.encode()).hexdigest()}
    (WORK/'equivalence.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(result.stdout,end='')

if __name__=='__main__': main()
