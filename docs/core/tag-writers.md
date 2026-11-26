# Tag Writers

`TagWriter` is a format-agnostic [port](ports.md) for updating an existing media
file in place. Its `write` method accepts the media path, parsed `TrackMetadata`,
and a local artwork path. The writer applies populated metadata fields and
embeds the image as the front cover using the file format's tagging conventions.

Implementations live in the
[tagging adapters](../../core/src/posidon_core/adapters/tagging), and the CLI
selects a writer for the requested output format. Writer classes satisfy the
`TagWriterFactory` port: they declare `supported_tag_versions` and a
`default_tag_version`, and their constructor takes a logger and an optional tag
version. The tagging stage passes `--tag-version` to the selected writer,
which validates the requested version when created. Format-specific decisions,
such as date frames and text encodings, stay in the adapter.

## MP3

For `mp3`, the CLI uses `Mp3TagWriter`, which manages Mutagen audio objects for
each write and saves the metadata and cover artwork together in one ID3 update.
It writes `id3v2.4` by default and also accepts `id3v2.3`. Each write:

1. Loads the existing frames untranslated, including an ID3v1 tag when the file
   has no ID3v2 tag.
2. Rewrites calendar-valid compact `YYYYMMDD` dates in TDRC, which earlier
   Posidon versions saved unchanged, as `YYYY-MM-DD`.
3. Converts every existing frame to the target version with Mutagen's
   `update_to_v23` or `update_to_v24`.
4. Applies the new text frames and front cover. New ID3v2.3 text uses UTF-16
   and new ID3v2.4 text uses UTF-8.
5. Saves once in the target version. An existing ID3v1 tag is updated, but
   none is added.

Debug logs show the input and output tag versions and the frame IDs that the
conversion removed or added.

Release dates must be calendar-valid `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or
`YYYYMMDD` values. ID3v2.4 stores the date in TDRC as an ISO date. ID3v2.3
first clears TYER, TDAT, TIME, and TRDA, so stale converted parts never attach
to the new date. It then writes the year to TYER and, for a full date, the day
and month to TDAT as `DDMM`. A year and month becomes a year only. A missing or
invalid release date leaves the existing, converted date unchanged.

ID3v2.3 is a compatibility tradeoff. It has no multi-value text frames, so the
writer joins lists such as artists, composers, and genres with `/`. A slash
inside a value is then indistinguishable from the separator. Converting to
ID3v2.3 also drops frames that exist only in ID3v2.4, such as TSOP and the
other sort-order frames. Posidon does not use the off-specification NUL
separator in ID3v2.3.
