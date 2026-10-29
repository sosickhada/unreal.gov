"""Daily entry point: enqueue once per Korean date; network work is worker-only."""
from bureau.config import Config
from bureau.store import Store


def main():
    config=Config.load()
    if config.env.get('AUTOMATION_PAUSED','0')=='1':
        print('Automation paused')
        return
    action=config.env.get('ACTION_TYPE','generate_trends')
    if action not in ('','generate_trends'):
        raise SystemExit('Use Telegram for explicit candidate selection/regeneration')
    print('Scheduled job',Store(config.db).schedule())


if __name__=='__main__':
    main()
