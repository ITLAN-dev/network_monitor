#!/usr/bin/env python3
"""
Монитор TIME_WAIT + Сетевая нагрузка (Гигабитная сеть)
Версия: 2.2 - ИСПРАВЛЕНА ОШИБКА С ФЛАГАМИ
"""

import psutil
import time
import logging
import argparse
import sys
from datetime import datetime
from collections import deque
import warnings

warnings.filterwarnings('ignore')

class NetworkMonitor:
    def __init__(self, threshold=1000, warning_threshold=500, 
                 interval=1, log_file=None, verbose=False,
                 network_threshold_mbps=900, network_warning_mbps=700,
                 quiet_mode=True):  # <-- НОВЫЙ ПАРАМЕТР
        """
        Args:
            verbose (bool): Показывать все проверки
            quiet_mode (bool): True - только предупреждения, False - всё
        """
        self.threshold = threshold
        self.warning_threshold = warning_threshold
        self.interval = interval
        self.verbose = verbose
        self.quiet_mode = quiet_mode  # <-- ТИХИЙ РЕЖИМ ТЕПЕРЬ УПРАВЛЯЕТСЯ ОТДЕЛЬНО
        self.network_threshold = network_threshold_mbps * 1024 * 1024
        self.network_warning = network_warning_mbps * 1024 * 1024
        
        self.tw_history = deque(maxlen=20)
        self.last_status = "NORMAL"
        self.silent_count = 0
        
        # Настройка логирования
        self.logger = logging.getLogger('NetworkMonitor')
        self.logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Статистика
        self.start_time = datetime.now()
        self.max_time_wait = 0
        self.max_network_speed = 0
        self.total_checks = 0
        self.alert_count = 0
        self.warning_count = 0
        self.net_alert_count = 0
        self.last_net_stats = None
        self.last_check_time = None
        
    def get_time_wait_count(self):
        try:
            connections = psutil.net_connections(kind='tcp')
            time_wait_count = sum(1 for c in connections if c.status == 'TIME_WAIT')
            
            stats = {}
            for conn in connections:
                stats[conn.status] = stats.get(conn.status, 0) + 1
                
            return time_wait_count, stats
            
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")
            return 0, {}
    
    def get_network_stats(self):
        try:
            net_io = psutil.net_io_counters()
            current_time = time.time()
            
            if self.last_net_stats and self.last_check_time:
                time_delta = current_time - self.last_check_time
                
                sent_delta = net_io.bytes_sent - self.last_net_stats.bytes_sent
                recv_delta = net_io.bytes_recv - self.last_net_stats.bytes_recv
                
                sent_mbps = (sent_delta / time_delta) * 8 / (1024 * 1024)
                recv_mbps = (recv_delta / time_delta) * 8 / (1024 * 1024)
                
                packets_sent_delta = net_io.packets_sent - self.last_net_stats.packets_sent
                packets_recv_delta = net_io.packets_recv - self.last_net_stats.packets_recv
                pps = (packets_sent_delta + packets_recv_delta) / time_delta
                
                errors = (net_io.errout - self.last_net_stats.errout + 
                         net_io.errin - self.last_net_stats.errin)
                drops = (net_io.dropout - self.last_net_stats.dropout + 
                        net_io.dropin - self.last_net_stats.dropin)
            else:
                sent_mbps = 0.0
                recv_mbps = 0.0
                pps = 0
                errors = 0
                drops = 0
            
            self.last_net_stats = net_io
            self.last_check_time = current_time
            
            if sent_mbps > self.max_network_speed:
                self.max_network_speed = sent_mbps
            if recv_mbps > self.max_network_speed:
                self.max_network_speed = recv_mbps
            
            return {
                'sent_mbps': sent_mbps,
                'recv_mbps': recv_mbps,
                'packets_per_sec': int(pps),
                'errors': errors,
                'drops': drops
            }
            
        except Exception as e:
            return {}
    
    def get_top_connections(self, limit=10):
        try:
            connections = psutil.net_connections(kind='tcp')
            timewait_conns = [c for c in connections if c.status == 'TIME_WAIT']
            
            if not timewait_conns:
                return []
            
            remote_hosts = {}
            for conn in timewait_conns:
                if conn.raddr:
                    key = f"{conn.raddr.ip}:{conn.raddr.port}"
                    remote_hosts[key] = remote_hosts.get(key, 0) + 1
            
            return sorted(remote_hosts.items(), key=lambda x: x[1], reverse=True)[:limit]
            
        except Exception:
            return []
    
    def get_dynamic_port_range(self):
        try:
            import subprocess
            result = subprocess.run(
                ['netsh', 'int', 'ipv4', 'show', 'dynamicport', 'tcp'],
                capture_output=True,
                text=True,
                encoding='cp866'
            )
            
            port_info = {}
            for line in result.stdout.split('\n'):
                if 'Start Port' in line:
                    port_info['start'] = int(line.split(':')[-1].strip())
                elif 'Number of Ports' in line:
                    port_info['count'] = int(line.split(':')[-1].strip())
            
            return port_info
            
        except Exception:
            return {}
    
    def log_detailed_stats(self, tw_count, stats, net_stats):
        """Полный вывод статистики (для вербозного режима)"""
        # Статус
        if tw_count >= self.threshold:
            status_emoji = "🔴"
            status_text = "КРИТИЧЕСКИЙ"
        elif tw_count >= self.warning_threshold:
            status_emoji = "🟡"
            status_text = "ПРЕДУПРЕЖДЕНИЕ"
        else:
            status_emoji = "🟢"
            status_text = "НОРМА"
        
        self.logger.info("=" * 70)
        self.logger.info(f"📊 СТАТУС: {status_emoji} {status_text}")
        self.logger.info(f"📈 TIME_WAIT: {tw_count} (макс: {self.max_time_wait})")
        
        if net_stats:
            self.logger.info(f"🌐 СЕТЬ:")
            self.logger.info(f"   📤 Отправка: {net_stats['sent_mbps']:.1f} Мбит/с")
            self.logger.info(f"   📥 Получение: {net_stats['recv_mbps']:.1f} Мбит/с")
            self.logger.info(f"   📦 Пакетов/с: {net_stats['packets_per_sec']}")
            if net_stats.get('errors', 0) > 0:
                self.logger.info(f"   ❌ Ошибки: {net_stats['errors']}")
            if net_stats.get('drops', 0) > 0:
                self.logger.info(f"   📦 Потери: {net_stats['drops']}")
        
        # Статистика TCP
        self.logger.info(f"🔌 TCP-соединения:")
        for status_name, cnt in sorted(stats.items()):
            if cnt > 0:
                if status_name == 'TIME_WAIT':
                    self.logger.info(f"   ⚠️ {status_name}: {cnt}")
                else:
                    self.logger.info(f"   {status_name}: {cnt}")
        
        # ТОП-5 если есть предупреждение
        if tw_count >= self.warning_threshold:
            top = self.get_top_connections(5)
            if top:
                self.logger.info(f"🎯 ТОП-5 удаленных хостов в TIME_WAIT:")
                for addr, cnt in top:
                    self.logger.info(f"   {addr}: {cnt}")
        
        self.logger.info("=" * 70)
    
    def check_and_log(self, tw_count, stats, net_stats):
        """Логирование с учетом режимов"""
        
        # Проверяем, есть ли проблемы
        has_issue = False
        issues = []
        
        # Проверка TIME_WAIT
        if tw_count >= self.threshold:
            has_issue = True
            issues.append(f"🚨 TIME_WAIT: {tw_count} (порог: {self.threshold})")
            self.alert_count += 1
            
            top = self.get_top_connections(5)
            if top:
                issues.append("  ТОП-5 удаленных адресов:")
                for addr, cnt in top:
                    issues.append(f"    {addr}: {cnt} соединений")
            
            port_info = self.get_dynamic_port_range()
            if port_info:
                usage = (tw_count / port_info.get('count', 1)) * 100
                issues.append(f"  Использование портов: {usage:.1f}%")
                
        elif tw_count >= self.warning_threshold:
            has_issue = True
            issues.append(f"⚠️ TIME_WAIT: {tw_count} (порог: {self.warning_threshold})")
            self.warning_count += 1
        
        # Проверка сети
        if net_stats:
            if net_stats['sent_mbps'] >= self.network_threshold / (1024 * 1024) * 8:
                has_issue = True
                issues.append(f"🚨 СЕТЬ: отправка {net_stats['sent_mbps']:.1f} Мбит/с (критично)")
                self.net_alert_count += 1
            elif net_stats['sent_mbps'] >= self.network_warning / (1024 * 1024) * 8:
                has_issue = True
                issues.append(f"⚠️ СЕТЬ: отправка {net_stats['sent_mbps']:.1f} Мбит/с")
            
            if net_stats['recv_mbps'] >= self.network_threshold / (1024 * 1024) * 8:
                has_issue = True
                issues.append(f"🚨 СЕТЬ: получение {net_stats['recv_mbps']:.1f} Мбит/с (критично)")
                self.net_alert_count += 1
            elif net_stats['recv_mbps'] >= self.network_warning / (1024 * 1024) * 8:
                has_issue = True
                issues.append(f"⚠️ СЕТЬ: получение {net_stats['recv_mbps']:.1f} Мбит/с")
            
            if net_stats.get('errors', 0) > 0:
                has_issue = True
                issues.append(f"❌ Ошибки сети: {net_stats['errors']}")
            if net_stats.get('drops', 0) > 0:
                has_issue = True
                issues.append(f"📦 Потерянные пакеты: {net_stats['drops']}")
        
        # ===== ЛОГИРОВАНИЕ =====
        
        # 1. Если ВЕРБОЗНЫЙ режим - показываем всё
        if self.verbose:
            self.log_detailed_stats(tw_count, stats, net_stats)
            return
        
        # 2. Если есть проблемы - показываем их
        if has_issue:
            status_emoji = "🔴" if tw_count >= self.threshold else "🟡"
            status_text = "CRITICAL" if tw_count >= self.threshold else "WARNING"
            
            first_line = f"{status_emoji} {status_text} | TIME_WAIT: {tw_count}"
            if net_stats:
                first_line += f" | ↑{net_stats['sent_mbps']:.1f} ↓{net_stats['recv_mbps']:.1f} Мбит/с"
                first_line += f" | PPS: {net_stats['packets_per_sec']}"
            
            self.logger.info(first_line)
            for issue in issues:
                self.logger.info(f"  {issue}")
            self.logger.info("---")
            return
        
        # 3. ТИХИЙ режим - показываем только краткий статус раз в 10 секунд
        self.silent_count += 1
        if self.silent_count % 10 == 0:
            net_str = ""
            if net_stats:
                net_str = f" | ↑{net_stats['sent_mbps']:.1f} ↓{net_stats['recv_mbps']:.1f} Мбит/с"
            self.logger.info(f"ℹ️ TIME_WAIT: {tw_count}{net_str}")
    
    def run(self):
        """Основной цикл мониторинга"""
        mode_text = "ВЕРБОЗНЫЙ" if self.verbose else "ТИХИЙ (только предупреждения)"
        
        self.logger.info("=" * 70)
        self.logger.info("🛰️  МОНИТОР TIME_WAIT + ГИГАБИТНАЯ СЕТЬ")
        self.logger.info(f"📌 TIME_WAIT: предупреждение {self.warning_threshold}, критично {self.threshold}")
        self.logger.info(f"🌐 СЕТЬ: предупреждение {self.network_warning/1024/1024:.0f} Мбит/с, критично {self.network_threshold/1024/1024:.0f} Мбит/с")
        self.logger.info(f"ℹ️  Режим: {mode_text}")
        self.logger.info("=" * 70)
        
        try:
            while True:
                try:
                    tw_count, stats = self.get_time_wait_count()
                    self.tw_history.append(tw_count)
                    
                    if tw_count > self.max_time_wait:
                        self.max_time_wait = tw_count
                    
                    net_stats = self.get_network_stats()
                    self.total_checks += 1
                    
                    self.check_and_log(tw_count, stats, net_stats)
                    
                    time.sleep(self.interval)
                    
                except KeyboardInterrupt:
                    self.logger.info("\n🛑 Остановлено пользователем")
                    break
                    
                except Exception as e:
                    self.logger.error(f"Ошибка: {e}")
                    time.sleep(self.interval)
                    
        except KeyboardInterrupt:
            self.logger.info("\n🛑 Остановлено пользователем")
        
        # Итог
        self.logger.info("=" * 70)
        self.logger.info("📊 ИТОГ")
        self.logger.info(f"⏱️  Время: {datetime.now() - self.start_time}")
        self.logger.info(f"📈 MAX TIME_WAIT: {self.max_time_wait}")
        self.logger.info(f"🌐 MAX скорость: {self.max_network_speed:.1f} Мбит/с")
        self.logger.info(f"⚠️ Предупреждений: {self.warning_count}")
        self.logger.info(f"🚨 Критических: {self.alert_count}")
        self.logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Монитор TIME_WAIT + Сеть (Гигабит)')
    parser.add_argument('-t', '--threshold', type=int, default=1000,
                        help='Критический порог TIME_WAIT (по умолчанию: 1000)')
    parser.add_argument('-w', '--warning', type=int, default=500,
                        help='Предупредительный порог TIME_WAIT (по умолчанию: 500)')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Интервал проверки в секундах (по умолчанию: 1)')
    parser.add_argument('-l', '--log-file', type=str, default=None,
                        help='Путь к файлу лога')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='ВЕРБОЗНЫЙ режим - показывать каждую проверку')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Максимально тихий режим (только критические ошибки)')
    parser.add_argument('-n', '--network-threshold', type=int, default=900,
                        help='Критическая нагрузка сети в Мбит/с (по умолчанию: 900)')
    parser.add_argument('-nw', '--network-warning', type=int, default=700,
                        help='Предупредительная нагрузка сети в Мбит/с (по умолчанию: 700)')
    
    args = parser.parse_args()
    
    # Логика выбора режима:
    # - Если указан -v -> вербозный
    # - Если указан -q -> максимально тихий
    # - Иначе -> тихий с кратким статусом каждые 10 сек
    verbose = args.verbose
    
    monitor = NetworkMonitor(
        threshold=args.threshold,
        warning_threshold=args.warning,
        interval=args.interval,
        log_file=args.log_file,
        verbose=verbose,  # <-- ТЕПЕРЬ ПРАВИЛЬНО ПЕРЕДАЕТСЯ
        network_threshold_mbps=args.network_threshold,
        network_warning_mbps=args.network_warning
    )
    
    try:
        monitor.run()
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()