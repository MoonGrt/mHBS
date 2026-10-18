"""Independent SHAKE256 stateful algorithms; no processor or recipe imports."""
def reference(family, hash_backend="shake"):
    if hash_backend != "shake" or family not in ("xmss", "lms"):
        raise ValueError("only standard SHAKE XMSS/LMS are supported")
    from model.reference import xmss, lms
    return xmss if family == "xmss" else lms
