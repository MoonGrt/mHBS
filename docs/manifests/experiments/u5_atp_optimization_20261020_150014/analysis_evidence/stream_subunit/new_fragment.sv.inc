            always_ff @(posedge clk) begin
                if (rst) fetched_valid <= 0;
                else if (stream_accept) begin
                    fetched_valid <= STREAM_ENABLE && state == STREAM;
                    if (STREAM_ENABLE && state == STREAM) begin
                        // Only one source is live for this beat. Capture the
                        // selected 16-byte window once instead of retaining
                        // both candidate windows until the padding stage.
                        fetched_payload <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                            position >= prefix_bytes ? list_window :
                            shapes[PREFIX_MESSAGE] ? source_window[143:16] : source_window[127:0];
                        fetched_prefix_head <= shapes[PREFIX_MESSAGE] && position == 0;
                        fetched_prefix_tail <= shapes[PREFIX_MESSAGE] && position == 16;
                        fetched_padding <= padding_reached;
                        fetched_partial <= partial_beat;
                        fetched_remaining <= remaining_bytes[3:0];
                        fetched_rate_tail <= beat == 8;
                        fetched_last <= stream_last;
                    end
                end
            end
`ifndef SYNTHESIS
            // Retain the former two-window stage as an independent simulation
            // oracle. It observes exactly the same fetch handshake and stall.
            logic [127:0] debug_fetched_source, debug_fetched_list;
            logic debug_fetched_use_list;
            always_ff @(posedge clk) begin : debug_stream_payload_snapshot
                if (!rst && stream_accept && STREAM_ENABLE && state == STREAM) begin
                    debug_fetched_source <= shapes[PREFIX_MESSAGE] ?
                        source_window[143:16] : source_window[127:0];
                    debug_fetched_list <= list_window;
                    debug_fetched_use_list <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                        position >= prefix_bytes;
                end
                if (!rst && fetched_valid && fetched_payload !==
                    (debug_fetched_use_list ? debug_fetched_list : debug_fetched_source))
                    $fatal(1, "selected stream payload differs from original two-window stage");
            end
`endif
            always_comb begin
                stream_data = fetched_payload;
                if (fetched_prefix_head) stream_data = identifier;
                else if (fetched_prefix_tail) stream_data[47:0] = {16'h8181, be32(leaf)};
                for (integer i = 0; i < 16; i++) begin
                    if (fetched_padding || (fetched_partial && fetched_remaining <= 4'(i)))
                        stream_data[i*8+:8] = 0;
                    if (!fetched_padding && fetched_partial && fetched_remaining == 4'(i))
                        stream_data[i*8+:8] = 8'h1f;
                    if (fetched_rate_tail) begin
                        if (i >= 8) stream_data[i*8+:8] = 0;
                        else if (i == 7 && fetched_last) stream_data[i*8+7] = 1'b1;
                    end
                end
            end

