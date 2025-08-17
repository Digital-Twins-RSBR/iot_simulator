from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
import sqlite3
import datetime
import shutil


class Command(BaseCommand):
    help = "Create a backup of the default sqlite database into initial_data/db.sqlite3"

    def handle(self, *args, **options):
        db_conf = settings.DATABASES.get('default', {})
        engine = db_conf.get('ENGINE', '')
        if 'sqlite3' not in engine:
            raise CommandError('backup_db supports only sqlite3 databases.')

        db_path = db_conf.get('NAME')
        if not db_path:
            raise CommandError('No sqlite database path configured in settings.')

        db_path = os.path.abspath(db_path)
        base_dir = getattr(settings, 'BASE_DIR', os.getcwd())
        dest_dir = os.path.join(base_dir, 'initial_data')
        os.makedirs(dest_dir, exist_ok=True)

        dest_path = os.path.join(dest_dir, 'db.sqlite3')
        ts = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
        dest_ts = os.path.join(dest_dir, f'db.sqlite3.{ts}')

        try:
            # Use sqlite3 backup API for a consistent copy even if DB is active
            src_conn = sqlite3.connect(db_path)
            dest_conn = sqlite3.connect(dest_path)
            with dest_conn:
                src_conn.backup(dest_conn)
            src_conn.close()
            dest_conn.close()

            # also keep a timestamped copy
            shutil.copy2(dest_path, dest_ts)

            # permissive perms
            try:
                os.chmod(dest_path, 0o664)
                os.chmod(dest_ts, 0o664)
            except Exception:
                pass

            self.stdout.write(self.style.SUCCESS(f'Backup created: {dest_path}'))
            self.stdout.write(self.style.SUCCESS(f'Timestamped copy: {dest_ts}'))
        except Exception as e:
            raise CommandError(f'Failed to create backup: {e}')
