#include "slh_dsa.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef SLH_EXPERIMENTAL
extern uint64_t sha2_256_compress_count;
extern uint64_t sha2_512_compress_count;
#else
static uint64_t sha2_256_compress_count;
static uint64_t sha2_512_compress_count;
#endif

static void write_file(const char *directory, const char *name,
                       const uint8_t *data, size_t length) {
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/%s", directory, name) >= (int)sizeof(path)) exit(2);
    FILE *file = fopen(path, "wb");
    if (!file || fwrite(data, 1, length, file) != length || fclose(file)) exit(2);
}

/* input.bin = SK.seed || SK.prf || PK.seed || opt_rand || message.
 * Every seed/randomness field has n=16 bytes, and message is 1..87 bytes.
 * Calls the independent local slhdsa-c internal API directly; no project model,
 * ROM, address formatter or recipe executor participates in this executable. */
int main(int argc, char **argv) {
    if (argc != 3 && argc != 4) { fprintf(stderr, "Usage: %s input.bin output_directory [external_signature.bin]\n", argv[0]); return 2; }
    uint8_t input[64+87+1], sk[64], pk[32], sig[17088], repeat[17088];
    FILE *file = fopen(argv[1], "rb");
    if (!file) return 2;
    size_t length = fread(input, 1, sizeof(input), file);
    if (ferror(file) || fclose(file) || length < 65 || length > 151) return 2;
    const slh_param_t *params = &slh_dsa_sha2_128f;
    sha2_256_compress_count = 0;
    sha2_512_compress_count = 0;
    if (slh_keygen_internal(sk, pk, input, input+16, input+32, params)) return 3;
    uint64_t keygen_blocks = sha2_256_compress_count;
    sha2_256_compress_count = 0;
    size_t sig_length = slh_sign_internal(sig, input+64, length-64, sk, input+48, params);
    uint64_t sign_blocks = sha2_256_compress_count;
    sha2_256_compress_count = 0;
    int verified = slh_verify_internal(input+64, length-64, sig, sig_length, pk, params);
    uint64_t verify_blocks = sha2_256_compress_count;
    sig[sig_length-1] ^= 1;
    int tamper_rejected = !slh_verify_internal(input+64, length-64, sig, sig_length, pk, params);
    sig[sig_length-1] ^= 1;
    input[64] ^= 1;
    int message_rejected = !slh_verify_internal(input+64, length-64, sig, sig_length, pk, params);
    input[64] ^= 1;
    size_t repeat_length = slh_sign_internal(repeat, input+64, length-64, sk, input+48, params);
    int repeat_matches = repeat_length == sig_length && !memcmp(repeat, sig, sig_length);
    int external_verified = -1, external_matches = -1;
    if (argc == 4) {
        file = fopen(argv[3], "rb");
        if (!file) return 2;
        size_t external_length = fread(repeat, 1, sizeof(repeat), file);
        int extra = fgetc(file);
        if (ferror(file) || fclose(file)) return 2;
        external_verified = extra == EOF && slh_verify_internal(input+64, length-64,
                              repeat, external_length, pk, params);
        external_matches = external_length == sig_length && !memcmp(repeat, sig, sig_length);
    }
    write_file(argv[2], "pk.bin", pk, sizeof(pk));
    write_file(argv[2], "sk.bin", sk, sizeof(sk));
    write_file(argv[2], "signature.bin", sig, sig_length);
    printf("{\"algorithm\":\"SLH-DSA-SHA2-128f\",\"interface\":\"internal\","
           "\"message_bytes\":%zu,\"signature_bytes\":%zu,\"public_key_bytes\":%zu,"
           "\"keygen_sha256_blocks\":%llu,\"sign_sha256_blocks\":%llu,"
           "\"verify_sha256_blocks\":%llu,\"sha512_blocks\":%llu,"
           "\"verified\":%s,\"signature_tamper_rejected\":%s,"
           "\"message_tamper_rejected\":%s,\"repeat_matches\":%s,"
           "\"external_signature_verified\":%s,\"external_signature_matches\":%s}\n",
           length-64, sig_length, sizeof(pk),
           (unsigned long long)keygen_blocks, (unsigned long long)sign_blocks,
           (unsigned long long)verify_blocks, (unsigned long long)sha2_512_compress_count,
           verified?"true":"false", tamper_rejected?"true":"false",
           message_rejected?"true":"false", repeat_matches?"true":"false",
           external_verified < 0 ? "null" : (external_verified ? "true" : "false"),
           external_matches < 0 ? "null" : (external_matches ? "true" : "false"));
    return !(verified && tamper_rejected && message_rejected && repeat_matches
             && external_verified != 0 && external_matches != 0);
}
