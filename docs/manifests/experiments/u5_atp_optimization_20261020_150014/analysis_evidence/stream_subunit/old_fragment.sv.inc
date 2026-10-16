            always_ff @(posedge clk) begin
                if (rst) fetched_valid <= 0;
                else if (stream_accept) begin
                    fetched_valid <= STREAM_ENABLE && state == STREAM;
                    if (STREAM_ENABLE && state == STREAM) begin
                        fetched_source <= shapes[PREFIX_MESSAGE] ?
                            source_window[143:16] : source_window[127:0];
                        fetched_list <= list_window;
                        fetched_use_list <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                            position >= prefix_bytes;
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
            always_comb begin
                stream_data = fetched_use_list ? fetched_list : fetched_source;
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

