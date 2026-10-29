// Minimal C ABI wrapper around the GDeflate reference decompressor
// (Apache-2.0, (c) NVIDIA Corporation / Microsoft Corporation),
// so that it can be called from Python through ctypes.
#include <stdint.h>
#include <stddef.h>

#include "GDeflate.h"

extern "C" __declspec(dllexport)
int scs_gdeflate_decompress(uint8_t *out, size_t out_size,
                            const uint8_t *in, size_t in_size)
{
    if (!out || !in || out_size == 0 || in_size == 0)
        return 0;
    return GDeflate::Decompress(out, out_size, in, in_size, 1) ? 1 : 0;
}

extern "C" __declspec(dllexport)
int scs_gdeflate_probe(uint8_t *out, size_t out_size,
                       const uint8_t *in, size_t in_size)
{
    // Convenience alias kept for symmetry with the Python binding layer.
    return scs_gdeflate_decompress(out, out_size, in, in_size);
}