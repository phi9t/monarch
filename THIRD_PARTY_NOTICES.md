# Third-party source notices

## SGLang OffloaderV1 excerpts

`scripts/glm52_sglang_offloader_patch.py` contains source-matching excerpts and
an adapted forward wrapper from SGLang's
[`python/sglang/srt/utils/offloader.py` at v0.5.17](https://github.com/sgl-project/sglang/blob/v0.5.17/python/sglang/srt/utils/offloader.py).

SGLang distributes this source under the
[Apache License, Version 2.0](third_party/licenses/Apache-2.0.txt). The excerpts
retain their upstream comments. Local adaptations match several wrapper
formats, move additional tensor attributes to the execution device, restore
those attributes after the call, and disable tied weights during the
functional call. These changes belong to the local patch helper.

The repository's root BSD license continues to apply to Monarch's own source;
it does not replace the Apache terms for these embedded SGLang portions.
