# Examples

## `portraits-demo`

A three-prompt folder that was run end to end against Ideogram, kept as a working
reference for the transparent-cut-out portrait case.

```bash
./imagegen-cli run examples/portraits-demo --chrome-profile ~/.chrome-ideogram-automation
```

The three prompts exercise the parts most likely to break: a square portrait, a
`3:4` portrait, and a `16:9` group shot with an explicit `size:` that forces a
downscale. Running them produced 2048x2048, 1728x2304 and 1920x1080 PNGs, each
with a genuine alpha channel (57-69% of pixels see-through).

Results land in `examples/portraits-demo/output/`, which is gitignored — generate
them yourself rather than pulling 11 MB of PNGs down with the clone. Rerunning
the command regenerates nothing; it adopts whatever is already there.

The phrasing that reliably produced alpha from Ideogram, at the end of each
prompt:

> …crisp clean edges, photorealistic, high detail, subject fully isolated on a
> completely transparent background, no backdrop, no ground shadow, no scenery.
