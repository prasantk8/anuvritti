# Family Continuity & Archive Recovery Guide

1. The entire family archive consists of one SQLite file (`anuvritti.db`) and one encrypted media directory (`media/`).
2. The media encryption key (`ANUVRITTI_MEDIA_KEY`) is stored in the family emergency envelope / 1Password emergency kit.
3. Daily off-site backups are mirrored to the family cloud storage remote at `~/backups/anuvritti-*` (or the encrypted USB disk).
4. To restore onto a new computer, install Docker (or Python 3.12+) and clone this repository.
5. Restore the snapshot by running `./scripts/restore.sh ~/backups/anuvritti-YYYYMMDD-HHMMSS var/anuvritti.db var/media`.
6. Start the archive container with `ANUVRITTI_MEDIA_KEY="<key>" make run` (or `docker run -e ANUVRITTI_MEDIA_KEY=...`).
7. Open `http://localhost:8000/docs` in any web browser to access the complete family API.
8. Export human-readable records anytime via `curl http://localhost:8000/v1/families/<family_id>/export -o family-archive.json`.
9. The yearly compilation films are rendered into `var/film/` and can be played directly with any standard video player.
10. This archive belongs to the family forever: no subscription, cloud account, or internet connection is required to read it.
