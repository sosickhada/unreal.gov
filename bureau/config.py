from dataclasses import dataclass
from pathlib import Path
import os
import shlex


@dataclass(frozen=True)
class Config:
    db: Path
    env: dict

    @classmethod
    def load(cls):
        values = {}
        path = Path(os.getenv('UNREAL_ENV_FILE', '/opt/unreal.gov/.env'))
        if path.is_file():
            for raw in path.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                key, sep, value = line.partition('=')
                if not sep or not key.strip().replace('_', '').isalnum():
                    raise ValueError('Invalid environment file syntax')
                parsed = shlex.split(value, comments=True)
                values[key.strip()] = ' '.join(parsed)
        values.update(os.environ)
        return cls(Path(values.get('UNREAL_DB', '/opt/unreal-github/unreal_bot.db')), values)

    def require_external(self):
        if self.env.get('ENABLE_EXTERNAL_CALLS') != '1' or self.env.get('AUTOMATION_PAUSED') == '1':
            raise RuntimeError('External calls disabled; enable only after operational approval')

    def integer(self, key, default):
        return int(self.env.get(key, default))
