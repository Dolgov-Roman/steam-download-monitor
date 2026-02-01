# steam-download-monitor

Скрипт на Python для отслеживания скорости загрузки/обновления игр в Steam. Работает независимо от места установки Steam (путь берётся из реестра Windows). Выводит в консоль текущую скорость, статус и название игры **каждую минуту в течение 5 минут**.

## Что умеет
- Находит папку Steam через реестр Windows (не зависит от диска/пути установки).
- Читает лог Steam: `logs/content_log.txt`.
- Определяет:
  - какая игра (AppID) сейчас скачивается/обновляется;
  - статус (DOWNLOADING / PAUSED / IDLE);
  - текущую скорость (`Current download rate: ... Mbps`);
  - прогресс загрузки (downloaded/total).
- Преобразует AppID в название игры через `steamapps/appmanifest_<appid>.acf`.
- Печатает результат раз в минуту (5 строк за 5 минут).

## Требования
- Windows
- Установленный Steam
- Python 3.9+ (подойдёт и новее)

## Статусы

- `DOWNLOADING` — скорость > 0 или в логе есть флаг загрузки
- `PAUSED` — приостановлено/ожидание (скорость = 0 и есть признаки паузы/остановки)
- `RUNNING_UPDATE` — идёт обновление (без активной загрузки)
- `DONE` — Steam сообщил, что обновление/загрузка завершены (дальше до конца 5 минут выводится DONE)
- `IDLE` — нет активности по выбранному AppID

## Запуск
1. Убедитесь, что в Steam идёт загрузка/обновление (иначе будет `No active Steam download/update detected`).
2. Запустите:
```bash
python monitor.py

## Как работает
- Путь Steam определяется через реестр Windows:
  - HKCU\Software\Valve\Steam\SteamPath (основной)
  - HKLM\SOFTWARE\WOW6432Node\Valve\Steam\InstallPath (fallback)
- Скрипт читает лог Steam `logs/content_log.txt` и извлекает:
  - скорость: `Current download rate: ... Mbps`
  - статус: `App update changed` / `state changed` (Downloading / Suspended и т.п.)
  - прогресс: `update started : download A/B`
- Название игры определяется по AppID через `steamapps/appmanifest_<appid>.acf`.

## Запуск в фоне 
### pythonw.exe (без окна консоли)
```bat
pythonw.exe monitor.py

## Ограничения
- Скрипт рассчитан на Windows + Steam.
- Опирается на формат строк в `content_log.txt`. При изменении формата логов Steam может потребоваться обновление регулярных выражений.

## Зависимости
Внешних зависимостей нет (только стандартная библиотека Python).


