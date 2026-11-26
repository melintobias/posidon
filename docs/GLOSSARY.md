# Posidon

Posidon retrieves recordings from the web and saves them as tagged audio files.
This glossary fixes the words used for its concepts in code, documentation, and
discussion.

## Language

**Source URL**:
An absolute URL, supplied by the user, that identifies exactly one recording to
retrieve as a **Track**.
_Avoid_: Link, input, URL

**Track**:
One recording that Posidon retrieves from one **Source URL** and saves as one
tagged audio file.
_Avoid_: Song, media item

**Retrieval**:
The step that extracts a **Track**'s metadata and downloads its media from its
**Source URL**.
_Avoid_: Acquisition, download

**Metadata lookup**:
The step that queries outside services for a **Track**'s metadata, beyond what
came with its **Source URL**.
_Avoid_: External metadata retrieval, enrichment

**Output directory**:
The directory that receives a run's finished **Tracks**.
_Avoid_: Destination, library, output dir

**Music directory**:
The platform's standard music folder, used as the **Output directory** when the
user doesn't choose one.
_Avoid_: Default directory, music folder
