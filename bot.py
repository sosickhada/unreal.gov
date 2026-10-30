"""Daily entry point: enqueue once per Korean date; network work is worker-only."""
from bureau.config import Config
from bureau.store import Store
import datetime as dt
from zoneinfo import ZoneInfo


def scheduled_window(instant):
    local=instant.astimezone(ZoneInfo("Asia/Seoul"))
    return local.hour==18 and local.minute<5



def main():
    config=Config.load()
    if config.env.get('AUTOMATION_PAUSED','0')=='1':
        print('Automation paused')
        return
    action=config.env.get('ACTION_TYPE','generate_trends')
    if action not in ('','generate_trends'):
        raise SystemExit('Use Telegram for explicit candidate selection/regeneration')
    if not scheduled_window(dt.datetime.now(dt.timezone.utc)):
        print('Outside 18:00–18:04 Asia/Seoul dispatch window; no catch-up enqueue')
        return
    print('Scheduled job',Store(config.db).schedule(source='vm_timer'))


if __name__=='__main__':
    main()
