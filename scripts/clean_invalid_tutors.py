from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.storage.database import get_connection, init_database
from scripts.audit_tutor_data import audit_profiles, load_profiles, quality_reasons, report_to_dict


def clean_invalid_tutors(dry_run: bool = True, reset_chroma: bool = False) -> dict[str, object]:
    init_database()
    profiles = load_profiles()
    invalid_profiles = [profile for profile in profiles if quality_reasons(profile)]
    invalid_ids = [profile.id for profile in invalid_profiles if profile.id]
    if not dry_run and invalid_ids:
        with get_connection() as connection:
            connection.executemany("DELETE FROM tutors WHERE id = ?", [(tutor_id,) for tutor_id in invalid_ids])
            connection.commit()
        if reset_chroma:
            chroma_path = Path(get_settings().chroma_path)
            if chroma_path.exists():
                shutil.rmtree(chroma_path)
    remaining = [profile for profile in profiles if profile.id not in set(invalid_ids)] if dry_run else load_profiles()
    return {
        "dry_run": dry_run,
        "deleted_count": 0 if dry_run else len(invalid_ids),
        "would_delete_count": len(invalid_ids),
        "deleted_names": [profile.name for profile in invalid_profiles],
        "reset_chroma": reset_chroma and not dry_run,
        "remaining_report": report_to_dict(audit_profiles(remaining)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove tutor records that fail the data-quality audit.")
    parser.add_argument("--apply", action="store_true", help="Actually delete invalid tutor records. Without this flag, only reports what would be deleted.")
    parser.add_argument("--reset-chroma", action="store_true", help="Delete the local Chroma index directory after removing invalid tutors so it can be rebuilt.")
    args = parser.parse_args()

    result = clean_invalid_tutors(dry_run=not args.apply, reset_chroma=args.reset_chroma)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
