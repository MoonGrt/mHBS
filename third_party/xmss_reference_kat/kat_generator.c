/* Deterministic driver for the RFC 8391 companion reference implementation. */
#include <openssl/sha.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "params.h"
#include "utils.h"
#include "xmss_core.h"

static void print_hex(const unsigned char *value, size_t length)
{
    size_t index;
    for (index = 0; index < length; index++) {
        printf("%02x", value[index]);
    }
}

int main(void)
{
    const uint32_t oid = 0x00000010;
    const uint32_t signing_index = 5;
    const unsigned char message[] = "micro-hbs-xmss-kat-v1";
    xmss_params params;
    unsigned char seed[96];
    unsigned char digest[SHA256_DIGEST_LENGTH];
    unsigned char wots_digest[SHA256_DIGEST_LENGTH];
    unsigned char auth_digest[SHA256_DIGEST_LENGTH];
    unsigned long long signed_length = 0;
    unsigned long long opened_length = 0;
    unsigned int index;
    int verify_result;

    if (xmss_parse_oid(&params, oid) != 0) {
        fprintf(stderr, "cannot parse XMSS OID\n");
        return 1;
    }

    unsigned char *public_key = calloc(params.pk_bytes, 1);
    unsigned char *secret_key = calloc(params.sk_bytes, 1);
    unsigned char *signed_message = calloc(params.sig_bytes + sizeof(message) - 1, 1);
    unsigned char *opened_message = calloc(params.sig_bytes + sizeof(message) - 1, 1);
    if (!public_key || !secret_key || !signed_message || !opened_message) {
        fprintf(stderr, "allocation failed\n");
        return 1;
    }

    for (index = 0; index < sizeof(seed); index++) {
        seed[index] = (unsigned char)index;
    }
    xmssmt_core_seed_keypair(&params, public_key, secret_key, seed);
    ull_to_bytes(secret_key, params.index_bytes, signing_index);
    if (xmss_core_sign(&params, secret_key, signed_message, &signed_length,
                       message, sizeof(message) - 1) != 0) {
        fprintf(stderr, "signing failed\n");
        return 1;
    }
    verify_result = xmss_core_sign_open(&params, opened_message, &opened_length,
                                        signed_message, signed_length, public_key);
    SHA256(signed_message, params.sig_bytes, digest);
    SHA256(signed_message + params.index_bytes + params.n,
           params.wots_sig_bytes, wots_digest);
    SHA256(signed_message + params.index_bytes + params.n + params.wots_sig_bytes,
           params.full_height * params.n, auth_digest);

    printf("{\n");
    printf("  \"schema_version\": 1,\n");
    printf("  \"profile\": \"XMSS-SHAKE256_10_256\",\n");
    printf("  \"oid\": \"00000010\",\n");
    printf("  \"upstream_commit\": \"171ccbd26f098542a67eb5d2b128281c80bd71a6\",\n");
    printf("  \"seed\": \""); print_hex(seed, sizeof(seed)); printf("\",\n");
    printf("  \"signing_index\": %u,\n", signing_index);
    printf("  \"message\": \""); print_hex(message, sizeof(message) - 1); printf("\",\n");
    printf("  \"public_key\": \""); print_hex(public_key, params.pk_bytes); printf("\",\n");
    printf("  \"randomizer\": \"");
    print_hex(signed_message + params.index_bytes, params.n); printf("\",\n");
    printf("  \"wots_signature_sha256\": \"");
    print_hex(wots_digest, sizeof(wots_digest)); printf("\",\n");
    printf("  \"authentication_path_sha256\": \"");
    print_hex(auth_digest, sizeof(auth_digest)); printf("\",\n");
    printf("  \"signature\": \""); print_hex(signed_message, params.sig_bytes); printf("\",\n");
    printf("  \"signature_sha256\": \""); print_hex(digest, sizeof(digest)); printf("\",\n");
    printf("  \"updated_index\": %u,\n",
           (unsigned int)bytes_to_ull(secret_key, params.index_bytes));
    printf("  \"signature_bytes\": %u,\n", params.sig_bytes);
    printf("  \"verify_result\": %d,\n", verify_result);
    printf("  \"opened_message_matches\": %s\n",
           opened_length == sizeof(message) - 1 &&
           memcmp(opened_message, message, sizeof(message) - 1) == 0 ? "true" : "false");
    printf("}\n");

    free(public_key);
    free(secret_key);
    free(signed_message);
    free(opened_message);
    return verify_result == 0 ? 0 : 1;
}
