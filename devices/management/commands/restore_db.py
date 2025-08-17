from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
import sqlite3
import datetime
import shutil


class Command(BaseCommand):
    help = "Restore the sqlite database from initial_data/db.sqlite3 into the configured database path"

    def add_arguments(self, parser):
        parser.add_argument('--keep-current-backup', action='store_true', help='Keep a timestamped backup of the current DB before restoring')

    def handle(self, *args, **options):
        db_conf = settings.DATABASES.get('default', {})
        engine = db_conf.get('ENGINE', '')
        if 'sqlite3' not in engine:
            raise CommandError('restore_db supports only sqlite3 databases.')

        db_path = db_conf.get('NAME')
        if not db_path:
            raise CommandError('No sqlite database path configured in settings.')

        db_path = os.path.abspath(db_path)
        base_dir = getattr(settings, 'BASE_DIR', os.getcwd())
        src_dir = os.path.join(base_dir, 'initial_data')
        src_path = os.path.join(src_dir, 'db.sqlite3')

        if not os.path.exists(src_path):
            raise CommandError(f'No backup found at {src_path}')

        # Optionally keep current DB
        if options.get('keep_current_backup') and os.path.exists(db_path):
            ts = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
            cur_backup = f"{db_path}.pre_restore.{ts}"
            try:
                shutil.copy2(db_path, cur_backup)
                try:
                    os.chmod(cur_backup, 0o664)
                except Exception:
                    pass
                self.stdout.write(self.style.SUCCESS(f'Current DB backed up to {cur_backup}'))
            except Exception as e:
                raise CommandError(f'Failed to keep current DB backup: {e}')

        try:
            # Use sqlite3 backup API: copy src -> dest
            src_conn = sqlite3.connect(src_path)
            dest_conn = sqlite3.connect(db_path)
            with dest_conn:
                src_conn.backup(dest_conn)
            src_conn.close()
            dest_conn.close()

            # permissive perms
            try:
                os.chmod(db_path, 0o664)
            except Exception:
                pass

            self.stdout.write(self.style.SUCCESS(f'Restored DB from {src_path} to {db_path}'))
        except Exception as e:
            raise CommandError(f'Failed to restore DB: {e}')
