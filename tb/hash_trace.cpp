// Simulation-only SHA-256 of every committed Hash context and digest.
#include <svdpi.h>
#include <openssl/evp.h>
#include <array>
#include <cstdint>
#include <cstdlib>

static EVP_MD_CTX *context = nullptr;
static unsigned sample_count = 0;
extern "C" void micro_trace_reset() {
    sample_count = 0;
    if (!context) context = EVP_MD_CTX_new();
    if (!context || EVP_DigestInit_ex(context, EVP_sha256(), nullptr) != 1) std::abort();
}
extern "C" void micro_trace_sample(unsigned long long recipe, unsigned layer,
    unsigned long long tree, unsigned leaf, unsigned a, unsigned b,
    const svBitVecVal *result) {
    std::array<unsigned char, 81> bytes{};
    unsigned pos = 0;
    auto append = [&](uint64_t value, unsigned length) {
        for (unsigned i = 0; i < length; ++i) bytes[pos++] = (value >> (8*i)) & 255;
    };
    append(recipe,8); append(layer,4); append(tree,8);
    append(leaf,4); append(a,4); append(b,4);
    unsigned output_bytes = (recipe >> 32) & 63;
    for (unsigned i = 0; i < 49; ++i)
        bytes[pos++] = i < output_bytes ? (result[i/4] >> (8*(i%4))) & 255 : 0;
    ++sample_count;
    if (pos != bytes.size() || EVP_DigestUpdate(context, bytes.data(), bytes.size()) != 1) std::abort();
}
// Stateful task framing extends the legacy 81-byte record with ADRS type.
extern "C" void micro_trace_sample_stateful(unsigned long long recipe, unsigned layer,
    unsigned long long tree, unsigned leaf, unsigned a, unsigned b,
    const svBitVecVal *result, unsigned address_type) {
    micro_trace_sample(recipe,layer,tree,leaf,a,b,result);
    std::array<unsigned char,4> bytes{};
    for(unsigned i=0;i<4;++i) bytes[i]=(address_type>>(8*i))&255;
    if(EVP_DigestUpdate(context,bytes.data(),bytes.size())!=1) std::abort();
}
extern "C" const char *micro_trace_digest() {
    static char output[65];
    unsigned char hash[32]; unsigned length = 0;
    EVP_MD_CTX *copy = EVP_MD_CTX_new();
    if (!copy || EVP_MD_CTX_copy_ex(copy, context) != 1 ||
        EVP_DigestFinal_ex(copy, hash, &length) != 1 || length != 32) std::abort();
    EVP_MD_CTX_free(copy);
    static const char hex[] = "0123456789abcdef";
    for (unsigned i=0; i<32; ++i) { output[2*i]=hex[hash[i]>>4]; output[2*i+1]=hex[hash[i]&15]; }
    output[64] = 0; return output;
}

extern "C" unsigned micro_trace_samples() { return sample_count; }
