// Simulation-only SHA-256 of every committed Hash context and digest.
#include <svdpi.h>
#include <openssl/evp.h>
#include <array>
#include <cstdint>
#include <cstdlib>

static EVP_MD_CTX *context = nullptr;
static EVP_MD_CTX *owner_context = nullptr;
static unsigned sample_count = 0;
static unsigned owner_count = 0;
extern "C" void micro_trace_reset() {
    sample_count = 0; owner_count = 0;
    if (!context) context = EVP_MD_CTX_new();
    if (!owner_context) owner_context = EVP_MD_CTX_new();
    if (!context || !owner_context || EVP_DigestInit_ex(context, EVP_sha256(), nullptr) != 1 ||
        EVP_DigestInit_ex(owner_context, EVP_sha256(), nullptr) != 1) std::abort();
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
static const char *digest_text(EVP_MD_CTX *source, char *output) {
    unsigned char hash[32]; unsigned length = 0;
    EVP_MD_CTX *copy = EVP_MD_CTX_new();
    if (!copy || EVP_MD_CTX_copy_ex(copy, source) != 1 ||
        EVP_DigestFinal_ex(copy, hash, &length) != 1 || length != 32) std::abort();
    EVP_MD_CTX_free(copy);
    static const char hex[] = "0123456789abcdef";
    for (unsigned i=0; i<32; ++i) { output[2*i]=hex[hash[i]>>4]; output[2*i+1]=hex[hash[i]&15]; }
    output[64] = 0; return output;
}

extern "C" const char *micro_trace_digest() {
    static char output[65]; return digest_text(context,output);
}

// A separate structural trace retains the owner of every accepted physical
// request, without changing the canonical VM/RTL Hash task trace format.
extern "C" void micro_owner_sample(unsigned owner, unsigned instance,
    unsigned kind, unsigned mode, unsigned stage, unsigned leaf, unsigned chain,
    unsigned level, unsigned step) {
    std::array<unsigned char,36> bytes{};
    const std::array<unsigned,9> fields={owner,instance,kind,mode,stage,leaf,chain,level,step};
    unsigned pos=0;
    for (unsigned value: fields)
        for (unsigned i=0;i<4;++i) bytes[pos++]=(value>>(8*i))&255;
    ++owner_count;
    if (!owner_context || EVP_DigestUpdate(owner_context,bytes.data(),bytes.size())!=1) std::abort();
}

extern "C" const char *micro_owner_digest() {
    static char output[65]; return digest_text(owner_context,output);
}

extern "C" unsigned micro_owner_samples() { return owner_count; }

extern "C" unsigned micro_trace_samples() { return sample_count; }
