# 🖥️ Monitor

Набор инструментов для мониторинга сетевых соединений, состояния системы и диагностики проблем с производительностью.

---

## 📂 Структура репозитория

Репозиторий содержит две версии мониторинга для разных задач:

### 1. [`network_monitor/`](./network_monitor) — базовая версия

**Лёгкий мониторинг сети и `TIME_WAIT`.**

* 📊 Отслеживание количества соединений в состоянии `TIME_WAIT`
* 🌐 Мониторинг скорости сети (отправка/получение в Мбит/с)
* 📦 Подсчёт пакетов в секунду (PPS)
* ⚠️ Пороговые предупреждения (настраиваемые)
* 🎯 Показ ТОП-5 удалённых хостов, создающих `TIME_WAIT`
* 💾 Отображение использования динамических портов
* 📝 Два режима работы: тихий и вербозный
* 🪟 Работает на Windows (Python 3.6+)

**Идеально подходит для:**

* Быстрой диагностики сетевых проблем
* Мониторинга исчерпания портов
* Обнаружения DDoS-подобных нагрузок

**[Подробнее →](./network_monitor/README.md)**

---

### 2. [`monitor_pro/`](./monitor_pro) — PRO версия

**Расширенный мониторинг системы и процессов.**

Все возможности базовой версии **+**:

* 🧠 **Мониторинг памяти по процессам** — RSS, VMS для ТОП-5 процессов
* 💻 **CPU по процессам** — реальная загрузка для каждого процесса
* 📊 **Системный CPU** — средняя нагрузка, по ядрам, Load Average
* 🔄 **Контекстные переключения** — диагностика проблем с драйверами
* 📈 **Тренды метрик** — анализ изменений за последние N секунд
* 🩺 **Автоматическая диагностика** — 8 типов проблем с версиями
* 💾 **Сохранение снапшотов** — JSON для анализа в Grafana/ELK
* ⚙️ **Гибкая настройка порогов** для всех метрик

**Идеально подходит для:**

* Поиска утечек памяти в приложениях
* Диагностики проблем с производительностью
* Глубокого анализа системных проблем
* Долгосрочного мониторинга серверов

**[Подробнее →](./monitor_pro/README.md)**

---

## 🚀 Быстрый старт

### Базовый запуск

```bash
# Базовая версия
cd network_monitor
py network_monitor.py

# PRO версия
cd monitor_pro
py monitor_pro.py -v
```

---

## 📊 Сравнение возможностей

| Возможность                  | Базовая версия | PRO версия |
| ---------------------------- | :------------: | :--------: |
| TIME_WAIT мониторинг         |        ✅       |      ✅     |
| Скорость сети (Мбит/с)       |        ✅       |      ✅     |
| Пакеты в секунду (PPS)       |        ✅       |      ✅     |
| ТОП-5 удалённых хостов       |        ✅       |      ✅     |
| Ошибки/потери пакетов        |        ✅       |      ✅     |
| **Память по процессам**      |        ❌       |      ✅     |
| **CPU по процессам**         |        ❌       |      ✅     |
| **Системный CPU**            |        ❌       |      ✅     |
| **Контекстные переключения** |        ❌       |      ✅     |
| **Тренды метрик**            |        ❌       |      ✅     |
| **Автодиагностика**          |        ❌       |      ✅     |
| **Снапшоты в JSON**          |        ❌       |      ✅     |

---

## 📦 Установка

### Общие требования

* Python 3.6 или выше
* Библиотека `psutil`

### Установка зависимостей

```bash
py -m pip install psutil
```

---

## 📋 Примеры использования

### Базовая версия — быстрый мониторинг сети

```bash
cd network_monitor
py network_monitor.py -v -t 1500 -w 800 -n 950 -nw 700
```

### PRO версия — полный анализ системы

```bash
cd monitor_pro

py monitor_pro.py -v \
  -t 15000 -w 8000 \
  -m 4096 -mw 2048 \
  -c 80 -cw 65 \
  -l monitor.log \
  -s ./snapshots
```

---

## 🛠️ Устранение неполадок

| Проблема                       | Решение                                             |
| ------------------------------ | --------------------------------------------------- |
| **`psutil` не установлен**     | `py -m pip install psutil`                          |
| **Ошибка доступа к процессам** | Запустите скрипт от имени администратора            |
| **CPU показывает `0.0%`**      | Это нормально для неактивных процессов в PRO-версии |

---

## 📄 Лицензия

**MIT License**

Copyright (c) 2026 Monitor PRO

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🤝 Вклад в проект


Если вы нашли баг или хотите предложить улучшение:

1. Создайте **Issue** с описанием проблемы.

2. Сделайте **Fork** репозитория.

3. Создайте ветку с новой функцией:

   ```bash
   git checkout -b feature/amazing-feature
   ```

4. Сделайте коммит:

   ```bash
   git commit -m "Add some amazing feature"
   ```

5. Отправьте **Pull Request**.

---

## 📞 Контакты

* **Автор:** ITLAN-dev
* **Email:** -
* **GitHub:** [github.com/ITLAN-dev](https://github.com/ITLAN-dev)

---

## ⭐ Поддержка проекта

Если этот инструмент помог вам в работе, поставьте звезду на GitHub! ⭐


---

**Выберите версию, которая лучше всего подходит для ваших задач!** 🚀

