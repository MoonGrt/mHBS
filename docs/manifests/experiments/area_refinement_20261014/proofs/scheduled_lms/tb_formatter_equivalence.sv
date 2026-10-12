`timescale 1ns/1ps
module original_formatter(input wire [255:0] ctx_public_seed,ctx_secret_seed,block_address,block_value,block_right,key_value,
 input wire [127:0] identifier,
 input wire [6:0] block_phase,
 input wire [3:0] block_shape,block_step,
 input wire [1:0] block_family,
 input wire block_pair,
 input wire [5:0] node_bytes,
 output wire [1599:0] unified_state);
function automatic [31:0] be32(input [31:0] v);
be32={v[7:0],v[15:8],v[23:16],v[31:24]}; endfunction
                begin : formatter
                    logic [255:0] f0, f1, f2, f3, masked_address;
                    logic [183:0] prefix;
                    logic [7:0] domain;
                    logic [1:0] layout;
                    logic two;
                    logic [1599:0] data;
                    wire seed = block_phase[0] || block_shape == 7;
                    wire prf = block_phase[2] || block_phase[3] || block_phase[5];
                    always_comb begin
                        masked_address = {
                            be32(block_phase[3] ? 32'd1 : block_phase[5] ? 32'd2 : 32'd0),
                            block_shape != 0 ? block_address[255:224] : be32({28'd0, block_step}),
                            block_address[223:192],
                            block_address[191:160],
                            block_address[159:128],
                            96'd0
                        };
                        f0 = ctx_public_seed;
                        f1 = block_address;
                        f2 = block_value;
                        f3 = block_right;
                        layout = 0;
                        two = block_pair;
                        prefix = 0;
                        domain = 0;
                        if (block_family == 1) begin
                            layout = 1;
                            domain = block_shape == 5 || prf ? 8'd3 :
                                seed ? 8'd4 : block_pair ? 8'd1 : 8'd0;
                            f1 = block_shape == 5 ? block_value :
                                seed ? ctx_secret_seed : prf ? ctx_public_seed : key_value;
                            f2 = block_shape == 5 ? {block_address[191:160], 224'd0} :
                                seed ? ctx_public_seed : prf ? masked_address : block_value;
                            f3 = seed ? masked_address : block_right;
                            two = seed || (block_pair && !prf);
                        end else if (block_family == 2) begin
                            if (block_shape == 14 || block_shape == 15) begin
                                layout = 3;
                                prefix = {
                                    8'd0,
                                    block_shape == 14 ? 16'h8282 : 16'h8383,
                                    block_address[255:224],
                                    identifier
                                };
                            end else begin
                                layout = 2;
                                two = 0;
                                prefix = {
                                    (seed || block_shape == 9) ? 8'hff : block_shape == 10 ?
                                        block_address[255:248] : {4'd0, block_step},
                                    block_address[223:216],
                                    8'd0,
                                    block_address[191:160],
                                    identifier
                                };
                            end
                            f1 = block_value;
                            f2 = block_right;
                        end
                        data = 0;
                        case (node_bytes)
                            16: begin
                                data[511:0] = {
                                    block_value[127:0], block_address, ctx_public_seed[127:0]
                                };
                                if (two) begin
                                    data[639:512] = block_right[127:0];
                                    data[647:640] = 8'h1f;
                                end else data[519:512] = 8'h1f;
                            end
                            24: begin
                                data[639:0] = {
                                    block_value[191:0], block_address, ctx_public_seed[191:0]
                                };
                                if (two) begin
                                    data[831:640] = block_right[191:0];
                                    data[839:832] = 8'h1f;
                                end else data[647:640] = 8'h1f;
                            end
                            default:
                            case (layout)
                                0: begin
                                    data[767:0] = {f2, f1, f0};
                                    if (two) begin
                                        data[1023:768]  = f3;
                                        data[1031:1024] = 8'h1f;
                                    end else data[775:768] = 8'h1f;
                                end
                                1: begin
                                    data[255:248] = domain;
                                    data[511:256] = f1;
                                    data[767:512] = f2;
                                    if (two) begin
                                        data[1023:768]  = f3;
                                        data[1031:1024] = 8'h1f;
                                    end else data[775:768] = 8'h1f;
                                end
                                2: begin
                                    data[183:0]   = prefix;
                                    data[439:184] = f1;
                                    data[447:440] = 8'h1f;
                                end
                                3: begin
                                    data[175:0]   = prefix[175:0];
                                    data[431:176] = f1;
                                    if (two) begin
                                        data[687:432] = f2;
                                        data[695:688] = 8'h1f;
                                    end else data[439:432] = 8'h1f;
                                end
                            endcase
                        endcase
                        data[1087] = 1;
                    end
                    assign unified_state = data;
                end

endmodule
module candidate_formatter(input wire [255:0] ctx_public_seed,ctx_secret_seed,block_address,block_value,block_right,key_value,
 input wire [127:0] identifier,
 input wire [6:0] block_phase,
 input wire [3:0] block_shape,block_step,
 input wire [1:0] block_family,
 input wire block_pair,
 input wire [5:0] node_bytes,
 output wire [1599:0] unified_state);
function automatic [31:0] be32(input [31:0] v);
be32={v[7:0],v[15:8],v[23:16],v[31:24]}; endfunction
                begin : formatter
                    logic [255:0] f0, f1, f2, f3, masked_address;
                    logic [183:0] prefix;
                    logic [7:0] domain;
                    logic [1:0] layout;
                    logic two;
                    logic [1599:0] data;
                    wire seed = block_phase[0] || block_shape == 7;
                    wire prf = block_phase[2] || block_phase[3] || block_phase[5];
                    always_comb begin
                        masked_address = {
                            be32(block_phase[3] ? 32'd1 : block_phase[5] ? 32'd2 : 32'd0),
                            block_shape != 0 ? block_address[255:224] : be32({28'd0, block_step}),
                            block_address[223:192],
                            block_address[191:160],
                            block_address[159:128],
                            96'd0
                        };
                        f0 = ctx_public_seed;
                        f1 = block_address;
                        f2 = block_value;
                        f3 = block_right;
                        layout = 0;
                        two = block_pair;
                        prefix = 0;
                        domain = 0;
                        if (block_family == 1) begin
                            layout = 1;
                            domain = block_shape == 5 || prf ? 8'd3 :
                                seed ? 8'd4 : block_pair ? 8'd1 : 8'd0;
                            f1 = block_shape == 5 ? block_value :
                                seed ? ctx_secret_seed : prf ? ctx_public_seed : key_value;
                            f2 = block_shape == 5 ? {block_address[191:160], 224'd0} :
                                seed ? ctx_public_seed : prf ? masked_address : block_value;
                            f3 = seed ? masked_address : block_right;
                            two = seed || (block_pair && !prf);
                        end else if (block_family == 2) begin
                            if (block_shape == 14 || block_shape == 15) begin
                                layout = 3;
                                prefix = {
                                    8'd0,
                                    block_shape == 14 ? 16'h8282 : 16'h8383,
                                    block_address[255:224],
                                    identifier
                                };
                            end else begin
                                layout = 2;
                                two = 0;
                                prefix = {
                                    (seed || block_shape == 9) ? 8'hff : block_shape == 10 ?
                                        block_address[255:248] : {4'd0, block_step},
                                    block_address[223:216],
                                    8'd0,
                                    block_address[191:160],
                                    identifier
                                };
                            end
                        end
                        data = 0;
                        case (node_bytes)
                            16: begin
                                data[511:0] = {
                                    block_value[127:0], block_address, ctx_public_seed[127:0]
                                };
                                if (two) begin
                                    data[639:512] = block_right[127:0];
                                    data[647:640] = 8'h1f;
                                end else data[519:512] = 8'h1f;
                            end
                            24: begin
                                data[639:0] = {
                                    block_value[191:0], block_address, ctx_public_seed[191:0]
                                };
                                if (two) begin
                                    data[831:640] = block_right[191:0];
                                    data[839:832] = 8'h1f;
                                end else data[647:640] = 8'h1f;
                            end
                            default:
                            case (layout)
                                0: begin
                                    data[767:0] = {f2, f1, f0};
                                    if (two) begin
                                        data[1023:768]  = f3;
                                        data[1031:1024] = 8'h1f;
                                    end else data[775:768] = 8'h1f;
                                end
                                1: begin
                                    data[255:248] = domain;
                                    data[511:256] = f1;
                                    data[767:512] = f2;
                                    if (two) begin
                                        data[1023:768]  = f3;
                                        data[1031:1024] = 8'h1f;
                                    end else data[775:768] = 8'h1f;
                                end
                                2: begin
                                    data[183:0]   = prefix;
                                    data[439:184] = block_value;
                                    data[447:440] = 8'h1f;
                                end
                                3: begin
                                    data[175:0]   = prefix[175:0];
                                    data[431:176] = block_value;
                                    if (two) begin
                                        data[687:432] = block_right;
                                        data[695:688] = 8'h1f;
                                    end else data[439:432] = 8'h1f;
                                end
                            endcase
                        endcase
                        data[1087] = 1;
                    end
                    assign unified_state = data;
                end

endmodule
module tb_formatter_equivalence;
 logic [255:0] ctx_public_seed,ctx_secret_seed,block_address,block_value,block_right,key_value;
 logic [127:0] identifier;
 logic [6:0] block_phase;
 logic [3:0] block_shape,block_step;
 logic [1:0] block_family;
 logic block_pair;
 logic [5:0] node_bytes;
 wire [1599:0] original_state,candidate_state;
 original_formatter original(.unified_state(original_state),.*);
 candidate_formatter candidate(.unified_state(candidate_state),.*);
 integer count=0;
 function automatic [255:0] rand256();
  for(integer j=0;j<8;j++) rand256[32*j+:32]=$urandom;
 endfunction
 initial begin
  for(integer fam=0;fam<4;fam++)
   for(integer shape=0;shape<16;shape++)
    for(integer phase=0;phase<128;phase++) begin
     block_family=2'(fam);block_shape=4'(shape);block_phase=7'(phase);
     block_step=4'($urandom);ctx_public_seed=rand256();ctx_secret_seed=rand256();
     block_address=rand256();block_value=rand256();block_right=rand256();key_value=rand256();
     identifier=128'(rand256());
     for(integer width=0;width<64;width++)
      for(integer pair=0;pair<2;pair++)begin
       node_bytes=6'(width);block_pair=1'(pair);#1;
       if(original_state!==candidate_state)
        $fatal(1,"Formatter differs family=%0d shape=%0d phase=%0d node_bytes=%0d pair=%0d",fam,shape,phase,width,pair);
       count++;
      end
    end
  $display("PASS formatter equivalence cases=%0d; exhaustive family/shape/phase/width/pair including malformed combinations",count);
  $finish;
 end
endmodule
