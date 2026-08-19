"""Command line interface.

    imagegen run <prompt-folder> [-o OUT] [--force-background-removal] ...
    imagegen status <prompt-folder>
    imagegen validate <prompt-folder>
    imagegen init <folder>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

from . import __version__, backends, manifest, prompts, ui
from .logging_utils import attach_file, log, rule
from .progress import Progress
from .prompts import PromptError
from .runner import RunLock, Runner

STATE_DIRNAME = ".imagegen"


def _paths(args) -> SimpleNamespace:
    """Resolve sources and output locations.

    Several sources may be given at once — seven manifests that between them
    describe one batch of 700 images are a single run, not seven. They are
    loaded in the order typed and share one output folder and one progress file.

    Output directory precedence: --out, then the manifests' own `output_dir`
    (which every manifest must agree on), then `<source>/output` for a single
    source. A manifest's path is taken relative to the manifest file itself, so
    the JSON stays portable — moving it moves its images.
    """
    raw = args.sources if isinstance(args.sources, list) else [args.sources]
    sources = []
    for item in raw:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"no such source: {path}")
        if path in sources:
            raise SystemExit(f"source given twice: {path}")
        sources.append(path)

    declared = []       # (source, absolute output dir it asked for)
    for source in sources:
        if not prompts.is_manifest(source):
            continue
        asked = manifest.output_dir_of(manifest.read(source))
        if asked:
            declared.append((source, (source.parent / Path(asked).expanduser()).resolve()))

    if getattr(args, "out", None):
        out_dir = Path(args.out).expanduser().resolve()
        declared_output = None
    elif len(declared) == len(sources) and len({d for _, d in declared}) == 1:
        out_dir = declared[0][1]
        declared_output = manifest.output_dir_of(manifest.read(sources[0]))
    elif len(sources) == 1:
        source = sources[0]
        out_dir = (source.parent if prompts.is_manifest(source) else source) / "output"
        declared_output = None
    else:
        # Silently picking one source's folder would scatter half the batch.
        asked = dict(declared)
        detail = "\n".join(
            f"  {s.name} → {asked[s]}" if s in asked
            else f"  {s.name} → (no output_dir; a prompt folder defaults to its own)"
            for s in sources
        )
        raise SystemExit(
            "these sources do not agree on one output folder, so pass -o/--out:\n"
            + detail
        )

    state_dir = out_dir / STATE_DIRNAME
    return SimpleNamespace(
        sources=sources,
        label=_label(sources),
        is_manifest=all(prompts.is_manifest(s) for s in sources),
        flat=bool(getattr(args, "flat", False)),
        declared_output=declared_output,
        out_dir=out_dir,
        state_dir=state_dir,
        state=Path(args.state).expanduser().resolve() if getattr(args, "state", None)
        else state_dir / "progress.json",
        log=state_dir / "run.log",
        lock=state_dir / "run.lock",
        debug=state_dir / "debug",
    )


def _label(sources: list[Path]) -> str:
    """A short name for the batch, used in the state file and status output."""
    if len(sources) == 1:
        return sources[0].name
    import os
    try:
        common = Path(os.path.commonpath([str(s) for s in sources]))
    except ValueError:
        common = sources[0].parent
    return f"{common.name or 'batch'} ({len(sources)} sources)"


def apply_config_defaults(args, parser, config: dict) -> list[str]:
    """Let `imagegen.yaml` set option defaults for this folder.

        options:
          chrome_profile: ~/.chrome-ideogram-automation
          force_background_removal: true

    Only options left at their built-in default are touched, so anything typed
    on the command line always wins.
    """
    options = config.get("options") or {}
    if not isinstance(options, dict):
        raise SystemExit("`options` in the folder config must be a mapping")
    builtin = {a.dest: a.default for a in parser._actions}
    applied = []
    for key, value in options.items():
        dest = key.replace("-", "_")
        if dest not in builtin:
            log(f"!! ignoring unknown option {key!r} in imagegen.yaml", err=True)
            continue
        if getattr(args, dest, None) == builtin[dest]:
            setattr(args, dest, value)
            applied.append(f"{dest}={value}")
    return applied


def _load(paths) -> list:
    jobs, errors = _load_all(paths)
    for path, message in errors:
        log(f"!! skipping {path.name}: {message}", err=True)
    for job in jobs:
        for warning in job.warnings:
            log(f"!  {job.rel_source}: {warning}", err=True)
    if not jobs:
        what = "images in" if paths.is_manifest else "prompt files under"
        raise SystemExit(f"no usable {what} "
                         + ", ".join(str(s) for s in paths.sources))
    return jobs


def _load_all(paths) -> tuple[list, list]:
    """Load every source into one job list, rejecting cross-source clashes.

    Two sources claiming the same id or the same output file would race each
    other into the same progress entry and the same PNG, so the second one is
    reported and dropped rather than half-overwriting the first.
    """
    jobs, errors = [], []
    seen_ids: dict[str, Path] = {}
    seen_out: dict[str, Path] = {}
    for source in paths.sources:
        loaded, source_errors = prompts.load_source(source, paths.out_dir)
        errors.extend(source_errors)
        for job in loaded:
            clash = seen_ids.get(job.id)
            if clash is not None and clash != source:
                errors.append((source, f"duplicate id {job.id!r} (also in {clash.name})"))
                continue
            clash = seen_out.get(job.rel_output)
            if clash is not None and clash != source:
                errors.append((source, f"duplicate output {job.rel_output!r} "
                                       f"(also from {clash.name})"))
                continue
            seen_ids[job.id] = source
            seen_out[job.rel_output] = source
            jobs.append(job)
    if paths.flat:
        # flattened once, over the whole batch: `a.json`'s icons/star.png and
        # `b.json`'s badges/star.png must see each other to be renamed apart
        prompts.flatten_outputs(jobs, paths.out_dir)
    return jobs, errors


def _select(jobs, args) -> list:
    if args.only:
        wanted = set(args.only)
        jobs = [j for j in jobs if j.id in wanted]
        missing = wanted - {j.id for j in jobs}
        if missing:
            raise SystemExit(f"no prompt with id: {', '.join(sorted(missing))}")
    if args.match:
        import fnmatch
        jobs = [j for j in jobs
                if any(fnmatch.fnmatch(j.id, p) or fnmatch.fnmatch(j.rel_source, p)
                       for p in args.match)]
    return jobs


def _sources_line(paths) -> str:
    if len(paths.sources) == 1:
        return str(paths.sources[0])
    return f"{paths.sources[0].parent}  ({len(paths.sources)} sources)"


def _merged_options(paths) -> dict:
    """Collect `options:` from every source; the last source to set a key wins.

    Only `options` merges. `defaults` stay per-source, because each manifest's
    defaults belong to its own prompts — one file's prompt_suffix must not leak
    into another's images.
    """
    options: dict = {}
    for source in paths.sources:
        if prompts.is_manifest(source):
            data = manifest.read(source)
            found = (data.get("options") or {}) if isinstance(data, dict) else {}
        else:
            found = prompts.load_config(source).get("options") or {}
        if not isinstance(found, dict):
            raise SystemExit(f"`options` in {source.name} must be a mapping")
        options.update(found)
    return {"options": options}


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_validate(args) -> int:
    paths = _paths(args)
    jobs, errors = _load_all(paths)
    for path, message in errors:
        print(f"ERROR  {path}: {message}")
    warned = [(j, w) for j in jobs for w in j.warnings]
    for job, warning in warned:
        print(f"WARN   {job.rel_source}: {warning}")
    kind = "manifest image(s)" if paths.is_manifest else "prompt(s)"
    print(f"\n{len(jobs)} valid {kind}, {len(errors)} error(s), "
          f"{len(warned)} warning(s)")
    if len(paths.sources) == 1:
        print(f"source  {paths.sources[0]}")
    else:
        from collections import Counter
        per = Counter(job.source for job in jobs)
        print(f"sources ({len(paths.sources)}):")
        for source in paths.sources:
            print(f"  {per.get(source, 0):>5}  {source}")
    print(f"output → {paths.out_dir}"
          + (f"  (from the manifest's output_dir: {paths.declared_output!r})"
             if paths.declared_output else "")
          + ("  [flat: no subfolders]" if paths.flat else ""))
    if jobs:
        j = jobs[0]
        preview = j.prompt if len(j.prompt) <= 300 else j.prompt[:300] + " …"
        print("\nFirst job:")
        print(f"  id         {j.id}")
        print(f"  source     {j.rel_source}")
        print(f"  output     {j.rel_output}")
        print(f"  size       {j.size or '(generator default)'}")
        print(f"  aspect     {j.aspect or '(generator default)'}")
        print(f"  background {j.background}")
        print(f"  prompt     {preview}")
    no_size = [j for j in jobs if j.size is None]
    if no_size:
        print(f"\nnote: {len(no_size)} prompt(s) declare no size; native output is kept")
    return 1 if errors else 0


def cmd_status(args) -> int:
    paths = _paths(args)
    if not paths.state.is_file():
        print(f"no run state yet at {paths.state}")
        return 0
    jobs = _load(paths)
    progress = Progress(paths.state, paths.label, args.backend)
    progress.sync(jobs)
    progress.reconcile(jobs)   # counts below must reflect what is really there
    counts = {"pending": 0, "done": 0, "failed": 0, "skipped": 0}
    for item in progress.data["items"].values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    total = sum(counts.values())
    done = counts["done"]
    pct = (done / total * 100) if total else 0
    print(f"{paths.label}: {done}/{total} done ({pct:.1f}%)  "
          f"pending {counts['pending']}  failed {counts['failed']}  skipped {counts['skipped']}")
    print(f"state   {paths.state}")
    print(f"output  {paths.out_dir}")
    if progress.data.get("last_completed_id"):
        print(f"last    {progress.data['last_completed_id']}")

    failures = [(i, item) for i, item in progress.data["items"].items()
                if item["status"] == "failed"]
    if failures:
        print(f"\nfailed ({len(failures)}) — rerun with --retry-failed:")
        for item_id, item in failures[:20]:
            print(f"  {item_id}: {(item.get('error') or '')[:140]}")
        if len(failures) > 20:
            print(f"  … and {len(failures) - 20} more")

    changed = [i for i, item in progress.data["items"].items() if item.get("prompt_changed")]
    if changed:
        print(f"\n{len(changed)} prompt(s) edited since generation — "
              f"rerun with --redo-changed to regenerate them")
    orphaned = [i for i, item in progress.data["items"].items() if item.get("orphaned")]
    if orphaned:
        print(f"{len(orphaned)} tracked item(s) no longer have a prompt file")
    return 0


def cmd_run(args) -> int:
    paths = _paths(args)
    if not args.dry_run:   # a dry run must not touch the output folder at all
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        attach_file(paths.log)

    config = _merged_options(paths)
    applied = apply_config_defaults(args, args._parser, config)
    paths.flat = bool(args.flat)   # imagegen.yaml may have just switched it on

    jobs = _load(paths)
    progress = Progress(paths.state, paths.label, args.backend)
    sync = progress.sync(jobs)
    adopted, requeued = progress.reconcile(jobs) if not args.no_reconcile else (0, 0)

    if args.retry_failed:
        n = progress.requeue(("failed",))
        log(f"re-queued {n} previously failed item(s)")
    if args.redo_changed:
        n = progress.requeue_changed()
        log(f"re-queued {n} item(s) whose prompt changed")
    if not args.dry_run:
        progress.save()

    selected = _select(jobs, args)
    queue = [j for j in selected if progress.get(j.id)["status"] == "pending"]

    rule("━")
    log(ui.paint(f"imagegen {__version__}", ui.C.BOLD, ui.C.CYAN)
        + ui.paint(f"  ·  {args.backend}  ·  {_sources_line(paths)}", ui.C.GREY))
    if len(paths.sources) > 1:
        for source in paths.sources:
            log(ui.paint("source   ", ui.C.GREY) + source.name)
    log(ui.paint("output   ", ui.C.GREY) + str(paths.out_dir)
        + (ui.paint("  (flat — no subfolders)", ui.C.GREY) if paths.flat else ""))
    log(ui.paint("prompts  ", ui.C.GREY)
        + f"{len(jobs)} total"
        + (f", {sync['added']} new" if sync["added"] else "")
        + (f", {sync['changed']} edited" if sync["changed"] else "")
        + (f", {adopted} adopted from disk" if adopted else "")
        + (ui.paint(f", {requeued} missing from disk", ui.C.YELLOW) if requeued else ""))
    # counted live: progress.counts is only refreshed on save, which a dry run skips
    done_now = sum(1 for j in jobs if progress.get(j.id)["status"] == "done")
    log(ui.paint("queue    ", ui.C.GREY) + ui.paint(f"{len(queue)}", ui.C.BOLD)
        + ui.paint(f" to generate · already done {done_now}/{len(jobs)}", ui.C.GREY))
    if applied:
        log(f"config   option defaults from the source(s): {', '.join(applied)}")
    if args.max_file_size is not None and args.max_file_size <= 0:
        raise SystemExit("--max-file-size must be a positive number of KB")
    if args.max_file_size:
        log(ui.paint(f"compressing any image over {args.max_file_size}KB "
                     "(resolution preserved)", ui.C.GREY))
    if args.force_background_removal:
        log("background removal is FORCED for every prompt that does not ask for an "
            "opaque background (images that already have alpha are left untouched)")
    rule("━")

    if args.dry_run:
        for job in queue[: args.limit or len(queue)]:
            log(f"would generate {job.id} ({job.aspect or 'default'}) -> {job.rel_output}")
        log(f"dry run: {len(queue)} item(s) would be generated")
        return 0
    if not queue:
        log("nothing to do — everything selected is already done")
        return 0

    backend_cls = backends.get(args.backend)
    backend = backend_cls(args)
    opts = SimpleNamespace(
        limit=args.limit,
        max_attempts=args.max_attempts,
        retry_backoff=args.retry_backoff,
        min_gap=args.min_gap,
        max_gap=max(args.max_gap, args.min_gap),
        force_background_removal=args.force_background_removal,
        allow_upscale=args.allow_upscale,
        max_file_bytes=args.max_file_size * 1024 if args.max_file_size else None,
        debug_dir=paths.debug,
    )

    with RunLock(paths.lock):
        stats = Runner(backend=backend, progress=progress, jobs=jobs, opts=opts).run(queue)

    rule("━")
    done, pending, failed = (progress.counts["done"], progress.counts["pending"],
                             progress.counts["failed"])
    log(ui.paint("session  ", ui.C.GREY)
        + ui.paint(f"✓ {stats.generated} generated", ui.C.GREEN)
        + (ui.paint(f"   ✗ {stats.failed} failed", ui.C.RED) if stats.failed else "")
        + (ui.paint("   (interrupted)", ui.C.YELLOW) if stats.interrupted else "")
        + ui.paint(f"   in {ui.duration(stats.elapsed)}", ui.C.GREY))
    log(ui.paint("total    ", ui.C.GREY) + ui.bar(done / max(1, len(jobs)), 18)
        + f"  {done}/{len(jobs)} done"
        + ui.paint(f" · {pending} pending", ui.C.GREY)
        + (ui.paint(f" · {failed} failed", ui.C.RED) if failed else ""))
    if pending or failed:
        log(ui.paint("rerun the same command to continue where this stopped", ui.C.GREY))
    if stats.fatal:
        return 2
    return 1 if stats.failed else 0


EXAMPLE_PROMPT = """---
id: 001-example
output: portraits/example.png
size: 1536x1536
aspect: "1:1"
background: transparent
negative: "watermark, text, extra fingers, blurry"
---
A polished studio portrait of a smiling woman in her thirties wearing a navy
blazer, three-quarter view, soft key light from the left, gentle rim light,
crisp edges, isolated subject on a fully transparent background, no backdrop,
no shadow on the ground, photorealistic, high detail.
"""

EXAMPLE_CONFIG = """# Defaults applied to every prompt file in this folder.
# Anything set in a prompt file's front-matter wins over these.
defaults:
  size: 1536x1536
  aspect: "1:1"
  background: transparent
  # prompt_suffix is appended to every prompt — handy for a shared style block.
  # prompt_suffix: "consistent studio lighting, premium finish"
"""


def cmd_convert(args) -> int:
    """Materialise a JSON manifest as a prompt folder of Markdown files."""
    import yaml

    source = Path(args.manifest).expanduser().resolve()
    if not prompts.is_manifest(source):
        raise SystemExit(f"{source} is not a .json manifest")
    target = Path(args.folder).expanduser().resolve()

    # Prompt files are laid out to mirror the images they produce, so the folder
    # reads the same way the output tree will.
    jobs, errors = prompts.load_source(source, target / "output")
    for label, message in errors:
        print(f"ERROR  {label}: {message}")
    if not jobs:
        raise SystemExit("nothing to convert")

    written = skipped = 0
    for job in jobs:
        dest = target / Path(job.rel_output).with_suffix(".md")
        if dest.exists() and not args.force:
            skipped += 1
            continue
        front = {"id": job.id, "output": job.rel_output}
        if job.size:
            front["size"] = f"{job.size[0]}x{job.size[1]}"
        if job.aspect:
            front["aspect"] = job.aspect
        if job.background != "unspecified":
            front["background"] = job.background
        if job.negative:
            front["negative"] = job.negative
        # safe_dump quotes what needs quoting — notably "1:1", which is not a
        # string to YAML unless it is quoted.
        header = yaml.safe_dump(front, sort_keys=False, allow_unicode=True,
                                default_flow_style=False, width=10**6)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"---\n{header}---\n\n{job.prompt}\n", encoding="utf-8")
        written += 1

    config = target / "imagegen.yaml"
    if not config.exists():
        config.write_text(
            f"# Generated from {source.name}.\n"
            "# Settings shared by every prompt go here; a prompt file's own\n"
            "# front-matter always wins over these.\n"
            "defaults: {}\n"
            "options: {}\n",
            encoding="utf-8",
        )

    print(f"\nwrote {written} prompt file(s) to {target}"
          + (f", skipped {skipped} that already existed (use --force to overwrite)"
             if skipped else ""))
    print(f"\nNext:  imagegen validate {target}\n       imagegen run {target}")
    return 1 if errors else 0


AUTHORING_FILE = "AUTHORING.md"


def cmd_spec(args) -> int:
    """Print the brief that turns an idea into a prompt folder."""
    # Installed, the brief sits beside this module; in a git checkout it is at
    # the repo root, where GitHub renders it.
    here = Path(__file__).resolve().parent
    path = next((c for c in (here / AUTHORING_FILE, here.parent / AUTHORING_FILE)
                 if c.is_file()), None)
    if path is None:
        print(f"{AUTHORING_FILE} is missing from {here}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    if not args.full:
        # Everything before the horizontal rule is instructions for the human
        # holding the terminal; the AI only needs what comes after it.
        _, sep, brief = text.partition("\n---\n")
        text = brief.lstrip() if sep else text
    if args.out:
        out = Path(args.out).expanduser()
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


def cmd_init(args) -> int:
    root = Path(args.prompt_dir).expanduser().resolve()
    (root / "portraits").mkdir(parents=True, exist_ok=True)
    config = root / "imagegen.yaml"
    example = root / "portraits" / "001-example.md"
    for path, content in ((config, EXAMPLE_CONFIG), (example, EXAMPLE_PROMPT)):
        if path.exists():
            print(f"kept existing {path}")
            continue
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path}")
    print(f"\nNext:  imagegen validate {root}\n       imagegen run {root}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imagegen",
        description="Universal, resumable batch image generation from a prompt folder.",
    )
    parser.add_argument("--version", action="version", version=f"imagegen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("sources", metavar="SOURCE", nargs="+",
                       help="a folder of prompt files, or one or more .json "
                            "manifests to run as a single batch")
        p.add_argument("-o", "--out", default=None,
                       help="output folder (default: <source>/output)")
        p.add_argument("--backend", default=backends.DEFAULT_BACKEND,
                       choices=sorted(backends.BACKENDS),
                       help=f"generator backend (default: {backends.DEFAULT_BACKEND})")
        p.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                       help="colour and live progress display (default: auto-detect)")
        p.add_argument("--flat", action="store_true",
                       help="write every image directly into the output folder "
                            "instead of category subfolders")

    p_run = sub.add_parser("run", help="generate everything still pending")
    add_common(p_run)
    p_run.add_argument("--state", default=None, help="override the progress file path")
    p_run.add_argument("--limit", type=int, default=0, help="stop after N successful images")
    p_run.add_argument("--only", action="append", default=[], metavar="ID",
                       help="generate just this id (repeatable)")
    p_run.add_argument("--match", action="append", default=[], metavar="GLOB",
                       help="only ids/paths matching this glob (repeatable)")
    p_run.add_argument("--retry-failed", action="store_true",
                       help="re-queue items that previously failed")
    p_run.add_argument("--redo-changed", action="store_true",
                       help="re-queue done items whose prompt file was edited since")
    p_run.add_argument("--no-reconcile", action="store_true",
                       help="do not adopt images already present on disk as done")
    p_run.add_argument("--force-background-removal", action="store_true",
                       help="after download, cut out the background when the image "
                            "came back with none (skipped when it is already transparent, "
                            "and for prompts that ask for an opaque background)")
    p_run.add_argument("--max-file-size", type=int, nargs="?", const=1200, default=None,
                       metavar="KB",
                       help="compress any image larger than this many KB, keeping its "
                            "resolution (bare flag = 1200 KB)")
    p_run.add_argument("--allow-upscale", action="store_true",
                       help="resize up to the requested size instead of keeping native")
    p_run.add_argument("--max-attempts", type=int, default=3, help="tries per image (default: 3)")
    p_run.add_argument("--retry-backoff", type=float, default=5.0,
                       help="seconds x attempt to wait before a retry")
    p_run.add_argument("--min-gap", type=float, default=4.0,
                       help="minimum pause between generations (default: 4s)")
    p_run.add_argument("--max-gap", type=float, default=9.0,
                       help="maximum pause between generations (default: 9s)")
    p_run.add_argument("--dry-run", action="store_true",
                       help="show what would be generated and exit")
    for cls in backends.BACKENDS.values():
        cls.add_arguments(p_run)
    # the run subparser carries its own option defaults, which
    # apply_config_defaults() needs to tell typed flags from untouched ones
    p_run.set_defaults(func=cmd_run, _parser=p_run)

    p_status = sub.add_parser("status", help="show progress for a prompt folder")
    add_common(p_status)
    p_status.add_argument("--state", default=None)
    p_status.set_defaults(func=cmd_status)

    p_val = sub.add_parser("validate", help="parse every prompt file and report problems")
    add_common(p_val)
    p_val.set_defaults(func=cmd_validate)

    p_spec = sub.add_parser(
        "spec",
        help="print the brief for turning an idea into a prompt folder",
        description="Print a copy-paste brief that any AI can follow to convert an "
                    "idea, discussion or design brief into a prompt folder this "
                    "tool can run.",
    )
    p_spec.add_argument("--out", default=None, metavar="FILE", help="write to a file instead of stdout")
    p_spec.add_argument("--full", action="store_true",
                        help="include the human-facing intro as well as the brief")
    p_spec.set_defaults(func=cmd_spec)

    p_convert = sub.add_parser(
        "convert", help="turn a JSON manifest into a prompt folder",
        description="Write one Markdown prompt file per image, laid out to mirror "
                    "the images the manifest describes. Only needed if you want to "
                    "hand-edit the prompts — `run` reads a manifest directly.")
    p_convert.add_argument("manifest", help="path to the .json manifest")
    p_convert.add_argument("folder", help="prompt folder to create")
    p_convert.add_argument("--force", action="store_true",
                           help="overwrite prompt files that already exist")
    p_convert.set_defaults(func=cmd_convert)

    p_init = sub.add_parser("init", help="scaffold a prompt folder")
    p_init.add_argument("prompt_dir")
    p_init.set_defaults(func=cmd_init)

    return parser


def _prepare_streams() -> None:
    """Never let an output character be the thing that kills a batch.

    The status line, the rules and the spinner are all non-ASCII. Piped into a
    file on a machine whose locale encoding is cp1252 — the Windows default —
    writing one raises UnicodeEncodeError, and a run that generated 300 images
    dies on a box-drawing glyph. UTF-8 where the stream allows it, and a
    replacement character rather than an exception where it does not.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _prepare_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    choice = getattr(args, "color", "auto")
    ui.configure(None if choice == "auto" else choice == "always")
    if getattr(args, "_parser", None) is None:
        args._parser = parser
    try:
        return args.func(args)
    except PromptError as exc:
        print(f"prompt error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
