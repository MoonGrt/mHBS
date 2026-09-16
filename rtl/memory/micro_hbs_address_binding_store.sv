`timescale 1ns/1ps
`default_nettype none

// Algorithm-independent address-binding side-table store.
//
// The 64-bit payload is consumed exactly as emitted by model/data_lowering.py:
//   [63:62] operand: 0=source_a, 1=source_b, 2=destination, 3=invalid
//   [61]    use_base_reg
//   [60:58] base_reg (R0..R7; must be zero when unused)
//   [57]    use_index_reg
//   [56:54] index_reg (R0..R7; must be zero when unused)
//   [53:38] base register scale in physical 64-bit words
//   [37:22] index stride in physical 64-bit words
//   [21:0]  reserved, must be zero
//
// The frozen Python payload has no embedded version bits, so its format
// version is supplied as configuration sideband and validated before commit.
// A binding must contain at least one enabled register term.  Enabled terms
// require a nonzero scale; disabled terms require zero register and scale.
module micro_hbs_address_binding_store #(
    parameter integer BINDING_COUNT = 64,
    parameter logic [7:0] FORMAT_VERSION = 8'h01
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         engine_busy,

    input  wire         cfg_valid,
    output wire         cfg_ready,
    input  wire [15:0]  cfg_binding_id,
    input  wire [7:0]   cfg_format_version,
    input  wire [63:0]  cfg_binding,
    output logic        cfg_error,
    output logic [15:0] cfg_error_code,

    input  wire         lookup_valid,
    output wire         lookup_ready,
    input  wire [15:0]  lookup_binding_id,
    output logic        lookup_rsp_valid,
    input  wire         lookup_rsp_ready,
    output logic        lookup_rsp_error,
    output logic [15:0] lookup_rsp_error_code,
    output logic [63:0] lookup_binding,

    output wire [1:0]   binding_operand,
    output wire         binding_use_base_reg,
    output wire [2:0]   binding_base_reg,
    output wire         binding_use_index_reg,
    output wire [2:0]   binding_index_reg,
    output wire [15:0]  binding_base_scale_words,
    output wire [15:0]  binding_index_stride_words,

    output wire         image_locked,
    output wire [31:0]  binding_capacity,
    output logic [31:0] configured_count,
    output logic [31:0] accepted_loads,
    output logic [31:0] rejected_loads,
    output logic [31:0] host_writes_busy,
    output logic [31:0] lookup_requests,
    output logic [31:0] lookup_errors
);
    localparam integer INDEX_WIDTH = (BINDING_COUNT <= 2)
        ? 1 : $clog2(BINDING_COUNT);
    localparam logic [16:0] BINDING_COUNT_EXT = 17'(BINDING_COUNT);

    localparam logic [15:0] ERR_CFG_BUSY       = 16'h0801;
    localparam logic [15:0] ERR_CFG_BOUNDS     = 16'h0802;
    localparam logic [15:0] ERR_CFG_CONFLICT   = 16'h0803;
    localparam logic [15:0] ERR_FORMAT_VERSION = 16'h0804;
    localparam logic [15:0] ERR_OPERAND         = 16'h0805;
    localparam logic [15:0] ERR_RESERVED        = 16'h0806;
    localparam logic [15:0] ERR_REGISTER        = 16'h0807;
    localparam logic [15:0] ERR_SCALE           = 16'h0808;
    localparam logic [15:0] ERR_LOOKUP_BOUNDS   = 16'h0809;
    localparam logic [15:0] ERR_UNINITIALIZED   = 16'h080a;

    (* ram_style = "distributed" *) logic [63:0]
        binding_memory [0:BINDING_COUNT-1];
    logic [BINDING_COUNT-1:0] binding_configured;

    wire cfg_id_in_range;
    wire lookup_id_in_range;
    wire cfg_operand_valid;
    wire cfg_reserved_valid;
    wire cfg_register_valid;
    wire cfg_scale_valid;
    wire cfg_write_commit;
    wire lookup_commit;
    wire [INDEX_WIDTH-1:0] cfg_memory_index;
    wire [INDEX_WIDTH-1:0] lookup_memory_index;

    wire cfg_use_base_reg = cfg_binding[61];
    wire [2:0] cfg_base_reg = cfg_binding[60:58];
    wire cfg_use_index_reg = cfg_binding[57];
    wire [2:0] cfg_index_reg = cfg_binding[56:54];
    wire [15:0] cfg_base_scale = cfg_binding[53:38];
    wire [15:0] cfg_index_stride = cfg_binding[37:22];

    assign image_locked = engine_busy;
    assign binding_capacity = BINDING_COUNT;
    // Lookup wins any same-cycle conflict and a stalled response provides
    // backpressure to new lookup requests without blocking IDLE image writes.
    assign cfg_ready = rst_n && !engine_busy && !lookup_valid;
    assign lookup_ready = rst_n
        && (!lookup_rsp_valid || lookup_rsp_ready);

    assign cfg_id_in_range = ({1'b0, cfg_binding_id}
        < BINDING_COUNT_EXT);
    assign lookup_id_in_range = ({1'b0, lookup_binding_id}
        < BINDING_COUNT_EXT);
    assign cfg_memory_index = cfg_binding_id[INDEX_WIDTH-1:0];
    assign lookup_memory_index = lookup_binding_id[INDEX_WIDTH-1:0];
    assign cfg_operand_valid = (cfg_binding[63:62] != 2'b11);
    assign cfg_reserved_valid = (cfg_binding[21:0] == 0);
    assign cfg_register_valid = (cfg_use_base_reg || cfg_base_reg == 0)
        && (cfg_use_index_reg || cfg_index_reg == 0);
    assign cfg_scale_valid = (cfg_use_base_reg || cfg_base_scale == 0)
        && (!cfg_use_base_reg || cfg_base_scale != 0)
        && (cfg_use_index_reg || cfg_index_stride == 0)
        && (!cfg_use_index_reg || cfg_index_stride != 0)
        && (cfg_use_base_reg || cfg_use_index_reg);
    assign cfg_write_commit = cfg_valid && cfg_ready && cfg_id_in_range
        && (cfg_format_version == FORMAT_VERSION) && cfg_operand_valid
        && cfg_reserved_valid && cfg_register_valid && cfg_scale_valid;
    assign lookup_commit = lookup_valid && lookup_ready;

    assign binding_operand = lookup_binding[63:62];
    assign binding_use_base_reg = lookup_binding[61];
    assign binding_base_reg = lookup_binding[60:58];
    assign binding_use_index_reg = lookup_binding[57];
    assign binding_index_reg = lookup_binding[56:54];
    assign binding_base_scale_words = lookup_binding[53:38];
    assign binding_index_stride_words = lookup_binding[37:22];

    initial begin
        if (BINDING_COUNT < 1 || BINDING_COUNT > 65536)
            $error("BINDING_COUNT must be in 1..65536");
    end

    // Keep the data array reset-free.  The reset validity map is the sole
    // authority for visibility, so stale or never-loaded words fail closed.
    always_ff @(posedge clk) begin
        if (cfg_write_commit)
            binding_memory[cfg_memory_index] <= cfg_binding;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            binding_configured <= '0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_rsp_error <= 1'b0;
            lookup_rsp_error_code <= '0;
            lookup_binding <= '0;
            configured_count <= '0;
            accepted_loads <= '0;
            rejected_loads <= '0;
            host_writes_busy <= '0;
            lookup_requests <= '0;
            lookup_errors <= '0;
        end else begin
            cfg_error <= 1'b0;
            cfg_error_code <= '0;

            if (lookup_rsp_valid && lookup_rsp_ready) begin
                lookup_rsp_valid <= 1'b0;
                lookup_rsp_error <= 1'b0;
                lookup_rsp_error_code <= '0;
                lookup_binding <= '0;
            end

            if (cfg_valid) begin
                if (engine_busy) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BUSY;
                    rejected_loads <= rejected_loads + 1'b1;
                    host_writes_busy <= host_writes_busy + 1'b1;
                end else if (lookup_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_CONFLICT;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_id_in_range) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BOUNDS;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (cfg_format_version != FORMAT_VERSION) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_FORMAT_VERSION;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_operand_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_OPERAND;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_reserved_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_RESERVED;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_register_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_REGISTER;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_scale_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_SCALE;
                    rejected_loads <= rejected_loads + 1'b1;
                end else begin
                    binding_configured[cfg_memory_index] <= 1'b1;
                    accepted_loads <= accepted_loads + 1'b1;
                    if (!binding_configured[cfg_memory_index])
                        configured_count <= configured_count + 1'b1;
                end
            end

            if (lookup_commit) begin
                lookup_rsp_valid <= 1'b1;
                lookup_requests <= lookup_requests + 1'b1;
                if (!lookup_id_in_range) begin
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_LOOKUP_BOUNDS;
                    lookup_binding <= '0;
                    lookup_errors <= lookup_errors + 1'b1;
                end else if (!binding_configured[lookup_memory_index]) begin
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_UNINITIALIZED;
                    lookup_binding <= '0;
                    lookup_errors <= lookup_errors + 1'b1;
                end else begin
                    lookup_rsp_error <= 1'b0;
                    lookup_rsp_error_code <= '0;
                    lookup_binding <= binding_memory[lookup_memory_index];
                end
            end
        end
    end
endmodule

`default_nettype wire
