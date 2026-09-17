`timescale 1ns/1ps
`default_nettype none

// Two 64-bit banks preserve the scalar Scratchpad contract and add one
// aligned consecutive-word read for the composer.  Scalar writes touch only
// their addressed bank; a pair read returns {word[address+1], word[address]}.
module micro_hbs_scratchpad64_banked #(
    parameter integer WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     request_valid,
    output logic                    request_ready,
    input  wire                     request_write,
    input  wire                     request_pair,
    input  wire [ADDRESS_WIDTH-1:0] request_address,
    input  wire [63:0]              request_write_data,
    output logic                    response_valid,
    output logic [63:0]             response_read_data,
    output logic [127:0]            response_read_pair,
    output logic                    bounds_error,
    input  wire                     scrub_start,
    output logic                    scrub_busy,
    output logic                    scrub_done
);
    localparam integer BANK_WORDS = (WORDS + 1) / 2;
    localparam integer BANK_ADDRESS_WIDTH = BANK_WORDS <= 2
        ? 1 : $clog2(BANK_WORDS);
    localparam integer WORDS_IS_POWER_OF_TWO = (WORDS & (WORDS - 1)) == 0;
    wire [63:0] bank0_read_data;
    wire [63:0] bank1_read_data;
    wire bank0_response_valid, bank1_response_valid;
    wire bank0_bounds_error, bank1_bounds_error;
    wire bank0_ready, bank1_ready;
    wire bank0_scrub_busy, bank1_scrub_busy;
    wire bank0_scrub_done, bank1_scrub_done;
    logic response_address_odd;
    logic response_was_pair;
    wire accepted = request_valid && request_ready;
    wire scalar_in_bounds;
    wire pair_in_bounds;
    generate
        if (WORDS_IS_POWER_OF_TWO && ADDRESS_WIDTH == $clog2(WORDS)) begin
            assign scalar_in_bounds = 1'b1;
            assign pair_in_bounds = !request_address[0];
        end else if (WORDS_IS_POWER_OF_TWO) begin
            assign scalar_in_bounds
                = request_address[ADDRESS_WIDTH-1:$clog2(WORDS)] == '0;
            // An aligned address below a power-of-two bound always leaves
            // room for its odd partner.
            assign pair_in_bounds = scalar_in_bounds && !request_address[0];
        end else begin
            assign scalar_in_bounds = request_address < WORDS;
            assign pair_in_bounds = !request_address[0]
                && ({1'b0, request_address} + 1'b1) < WORDS;
        end
    endgenerate
    wire read_enable = accepted && !request_write
        && (request_pair ? pair_in_bounds : scalar_in_bounds);
    wire write_enable = accepted && request_write && !request_pair
        && scalar_in_bounds;
    wire [BANK_ADDRESS_WIDTH-1:0] bank_address
        = request_address[BANK_ADDRESS_WIDTH:1];
    wire bank0_request_valid = (read_enable
        && (request_pair || !request_address[0]))
        || (write_enable && !request_address[0]);
    wire bank1_request_valid = (read_enable
        && (request_pair || request_address[0]))
        || (write_enable && request_address[0]);

    assign request_ready = bank0_ready && bank1_ready && !scrub_start;
    assign response_valid = response_was_pair
        ? (bank0_response_valid && bank1_response_valid)
        : (response_address_odd
           ? bank1_response_valid : bank0_response_valid);
    assign response_read_data = response_address_odd
        ? bank1_read_data : bank0_read_data;
    assign response_read_pair = {bank1_read_data, bank0_read_data};
    assign scrub_busy = bank0_scrub_busy || bank1_scrub_busy;
    assign scrub_done = bank0_scrub_done && bank1_scrub_done;

    initial begin
        if (WORDS < 2 || WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid banked Scratchpad WORDS/ADDRESS_WIDTH");
    end

    // Preserve the exact reset-free, one-array/one-clock-process RAM template
    // already used by micro_hbs_scratchpad64.  A wrapper-level bank select is
    // deliberately kept out of the array process so Vivado can infer one
    // RAMB36 per 512x64 bank instead of expanding both banks into LUTRAM.
    micro_hbs_scratchpad64 #(
        .WORDS(BANK_WORDS), .ADDRESS_WIDTH(BANK_ADDRESS_WIDTH)
    ) bank0_memory (
        .clk, .rst_n, .request_valid(bank0_request_valid),
        .request_ready(bank0_ready), .request_write(write_enable),
        .request_address(bank_address),
        .request_write_data(request_write_data),
        .response_valid(bank0_response_valid),
        .response_read_data(bank0_read_data),
        .bounds_error(bank0_bounds_error), .scrub_start,
        .scrub_busy(bank0_scrub_busy), .scrub_done(bank0_scrub_done)
    );

    micro_hbs_scratchpad64 #(
        .WORDS(BANK_WORDS), .ADDRESS_WIDTH(BANK_ADDRESS_WIDTH)
    ) bank1_memory (
        .clk, .rst_n, .request_valid(bank1_request_valid),
        .request_ready(bank1_ready), .request_write(write_enable),
        .request_address(bank_address),
        .request_write_data(request_write_data),
        .response_valid(bank1_response_valid),
        .response_read_data(bank1_read_data),
        .bounds_error(bank1_bounds_error), .scrub_start,
        .scrub_busy(bank1_scrub_busy), .scrub_done(bank1_scrub_done)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bounds_error <= 1'b0;
            response_address_odd <= 1'b0;
            response_was_pair <= 1'b0;
        end else begin
            if (read_enable) begin
                response_address_odd <= request_address[0];
                response_was_pair <= request_pair;
            end
            bounds_error <= accepted
                && (!(request_pair ? pair_in_bounds : scalar_in_bounds)
                    || (request_pair && request_write));
        end
    end
endmodule

`default_nettype wire
