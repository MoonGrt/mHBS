/* Validation only: upstream XMSS signer and Cisco LMS verifier; no ROM recipes. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "params.h"
#include "xmss_core.h"
#include "lm_verify.h"
#include "lms/hash.h"
#include <openssl/evp.h>

uint64_t ref_hashes, ref_perms;
void ref_count(size_t length) { ref_hashes++; ref_perms += length / 136 + 1; }
static void be(unsigned char *p, uint32_t v, int n) {
    for (int i=n-1;i>=0;i--) {p[i]=(unsigned char)v;v>>=8;}
}
static uint32_t read32(const unsigned char *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
/* Cisco's original algorithms call this API. Only the SHAKE backend is added. */
void hss_zeroize(void *p,size_t n) { memset(p,0,n); }
void hss_init_hash_context(int h, union hash_context *c) {
    if(h==1) {SHA256_Init(&c->sha256);return;}
    c->shake=EVP_MD_CTX_new(); if(!c->shake)abort();
    if(EVP_DigestInit_ex(c->shake,EVP_shake256(),NULL)!=1)abort();
    c->shake_bytes=0;
}
void hss_update_hash_context(int h,union hash_context *c,const void *p,size_t n) {
    if(h==1) {SHA256_Update(&c->sha256,p,n);return;}
    if(EVP_DigestUpdate(c->shake,p,n)!=1)abort(); c->shake_bytes+=n;
}
void hss_finalize_hash_context(int h,union hash_context *c,void *p) {
    if(h==1) {SHA256_Final(p,&c->sha256);return;}
    if(EVP_DigestFinalXOF(c->shake,p,32)!=1)abort();
    ref_count(c->shake_bytes);EVP_MD_CTX_free(c->shake);c->shake=NULL;
}
void hss_hash_ctx(void *out,int h,union hash_context *c,const void *p,size_t n) {
    hss_init_hash_context(h,c);hss_update_hash_context(h,c,p,n);hss_finalize_hash_context(h,c,out);
}
void hss_hash(void *out,int h,const void *p,size_t n) {
    union hash_context c;hss_hash_ctx(out,h,&c,p,n);
}
unsigned hss_hash_length(int h) {return h==1||h==2 ? 32 : 0;}
unsigned hss_hash_blocksize(int h) {return h==1 ? 64 : h==2 ? 136 : 0;}
static void H(unsigned char *out,const unsigned char *in,size_t n) {hss_hash(out,2,in,n);}

int ref_xmss_verify(int height,const unsigned char *pk,const unsigned char *sig,
                   const unsigned char *m,size_t mlen) {
    xmss_params p;uint32_t oid=height==10?16:height==16?17:18;
    if(read32(pk)!=oid || xmss_parse_oid(&p,oid))return 0;
    unsigned char sm[4096],opened[4096];unsigned long long len;
    memcpy(sm,sig,p.sig_bytes);memcpy(sm+p.sig_bytes,m,mlen);
    return !xmssmt_core_sign_open(&p,opened,&len,sm,p.sig_bytes+mlen,pk+4)
        && len==mlen && !memcmp(opened,m,mlen);
}
int ref_lms_verify(const unsigned char *pk,const unsigned char *sig,size_t slen,
                   const unsigned char *m,size_t mlen) {
    return lm_validate_signature(pk,m,mlen,0,sig,slen);
}
int ref_xmss_generate(int height,uint32_t q,const unsigned char *seed,
                     const unsigned char *m,size_t mlen,unsigned char *pk,
                     unsigned char *sig,uint64_t counts[4]) {
    xmss_params p;uint32_t oid=height==10?16:height==16?17:18;
    if(xmss_parse_oid(&p,oid) || q>=(1u<<height))return -1;
    unsigned char sk[256],sm[4096];unsigned long long len;
    ref_hashes=ref_perms=0;be(pk,oid,4);
    xmssmt_core_seed_keypair(&p,pk+4,sk,(unsigned char*)seed);
    counts[0]=ref_hashes;counts[1]=ref_perms;
    be(sk,q,p.index_bytes);ref_hashes=ref_perms=0;
    if(xmssmt_core_sign(&p,sk,sm,&len,m,mlen))return -2;
    memcpy(sig,sm,p.sig_bytes);counts[2]=ref_hashes;counts[3]=ref_perms;
    return ref_xmss_verify(height,pk,sig,m,mlen) ? 0 : -3;
}
static void lms_chain(unsigned char *out,const unsigned char *I,const unsigned char *seed,
                      uint32_t q,unsigned i,unsigned steps) {
    unsigned char in[55];memcpy(in,I,16);be(in+16,q,4);be(in+20,i,2);
    in[22]=255;memcpy(in+23,seed,32);H(in+23,in,55);
    for(unsigned j=0;j<steps;j++) {in[22]=(unsigned char)j;H(in+23,in,55);}
    memcpy(out,in+23,32);
}
static void lms_tree(int height,uint32_t target,const unsigned char *I,const unsigned char *seed,
                     unsigned char root[32],unsigned char *auth) {
    unsigned char stack[21][32],endpoints[22+67*32],in[86];unsigned levels[21],used=0;
    memcpy(endpoints,I,16);endpoints[20]=endpoints[21]=128;
    for(uint32_t q=0;q<(1u<<height);q++) {
        be(endpoints+16,q,4);
        for(unsigned i=0;i<67;i++)lms_chain(endpoints+22+32*i,I,seed,q,i,15);
        H(in+22,endpoints,sizeof endpoints);memcpy(in,I,16);be(in+16,(1u<<height)+q,4);
        in[20]=in[21]=130;H(stack[used],in,54);levels[used++]=0;
        if(q==(target^1u))memcpy(auth,stack[used-1],32);
        while(used>=2 && levels[used-1]==levels[used-2]) {
            unsigned level=levels[used-1]+1;uint32_t index=q>>level;
            memcpy(in,I,16);be(in+16,((1u<<height)+q)>>level,4);in[20]=in[21]=131;
            memcpy(in+22,stack[used-2],32);memcpy(in+54,stack[used-1],32);
            H(stack[used-2],in,86);used--;levels[used-1]=level;
            if(level<(unsigned)height && index==((target>>level)^1u))memcpy(auth+32*level,stack[used-1],32);
        }
    }
    memcpy(root,stack[0],32);
}
int ref_lms_generate(int height,uint32_t q,const unsigned char *seed,const unsigned char *I,
                    const unsigned char *C,const unsigned char *m,size_t mlen,
                    unsigned char *pk,unsigned char *sig,uint64_t counts[4]) {
    if(q>=(1u<<height))return -1;
    unsigned char auth[640],root[32],in[141],digest[32];unsigned digits[67],sum=0;
    uint32_t type=height==10?16:height==15?17:18;
    ref_hashes=ref_perms=0;lms_tree(height,q,I,seed,root,auth);
    counts[0]=ref_hashes;counts[1]=ref_perms;be(pk,type,4);be(pk+4,11,4);
    memcpy(pk+8,I,16);memcpy(pk+24,root,32);
    ref_hashes=ref_perms=0;memcpy(in,I,16);be(in+16,q,4);in[20]=in[21]=129;
    memcpy(in+22,C,32);memcpy(in+54,m,mlen);H(digest,in,54+mlen);
    for(unsigned i=0;i<64;i++) {digits[i]=(digest[i/2]>>(i%2?0:4))&15;sum+=15-digits[i];}
    digits[64]=(sum>>8)&15;digits[65]=(sum>>4)&15;digits[66]=sum&15;
    be(sig,q,4);be(sig+4,11,4);memcpy(sig+8,C,32);
    for(unsigned i=0;i<67;i++)lms_chain(sig+40+32*i,I,seed,q,i,digits[i]);
    be(sig+2184,type,4);memcpy(sig+2188,auth,32*height);
    /* Sign deliberately repeats the full tree, matching the RTL's cold path. */
    lms_tree(height,q,I,seed,root,auth);
    counts[2]=ref_hashes;counts[3]=ref_perms;
    return ref_lms_verify(pk,sig,2188+32*height,m,mlen) ? 0 : -3;
}
