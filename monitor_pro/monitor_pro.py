#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Network Monitor PRO - Расширенный мониторинг TIME_WAIT, памяти, CPU и процессов
Версия: 2.3 - Исправлен сбор CPU для Windows
"""

import psutil
import time
import argparse
import logging
import sys
import json
import os
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

# ==================== КОНФИГУРАЦИЯ ====================
@dataclass
class Config:
    """Конфигурация монитора"""
    # Пороги TIME_WAIT
    tw_threshold: int = 1000
    tw_warning: int = 500
    
    # Пороги сети (Мбит/с)
    net_threshold: int = 950
    net_warning: int = 700
    
    # Пороги памяти (МБ)
    mem_threshold_mb: int = 1024
    mem_warning_mb: int = 512
    
    # Пороги CPU (%)
    cpu_threshold: int = 80
    cpu_warning: int = 60
    
    # Интервалы
    interval: float = 1.0
    trend_window: int = 60
    cpu_sample_interval: float = 1.0  # Интервал для сбора CPU
    
    # Флаги
    verbose: bool = False
    quiet: bool = False
    log_file: Optional[str] = None
    snapshot_dir: Optional[str] = "snapshots"
    
    # Лимиты
    top_processes: int = 5
    top_connections: int = 5
    
    # Настройки алертов
    alert_cooldown: int = 60
    status_interval: int = 60

# ==================== СТАТИСТИКА ====================
class TrendAnalyzer:
    """Анализ трендов метрик"""
    
    def __init__(self, window_size: int = 60):
        self.window_size = window_size
        self.history: deque = deque(maxlen=window_size)
    
    def add_value(self, value: float):
        self.history.append(value)
    
    def get_trend(self) -> Optional[float]:
        if len(self.history) < 2:
            return None
        first = self.history[0]
        last = self.history[-1]
        if first == 0:
            return None
        return ((last - first) / first) * 100
    
    def get_delta(self) -> Optional[float]:
        if len(self.history) < 2:
            return None
        return self.history[-1] - self.history[0]

# ==================== МОНИТОРИНГ ====================
class NetworkMonitor:
    """Основной класс мониторинга"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = self._setup_logging()
        
        self.trends = {
            'timewait': TrendAnalyzer(config.trend_window),
            'memory': {},
            'cpu': TrendAnalyzer(config.trend_window),
            'net_up': TrendAnalyzer(config.trend_window),
            'net_down': TrendAnalyzer(config.trend_window),
            'pps': TrendAnalyzer(config.trend_window),
            'errors': TrendAnalyzer(config.trend_window),
        }
        
        self.prev_net = None
        self.prev_time = None
        
        self._last_alert_time = {}
        self._alert_cooldown = config.alert_cooldown
        self._last_issue_hash = None
        self._last_issue_time = 0
        self._status_counter = 0
        self._cpu_cache = {}
        
        if config.snapshot_dir and not os.path.exists(config.snapshot_dir):
            os.makedirs(config.snapshot_dir)
    
    def _setup_logging(self):
        logger = logging.getLogger('NetworkMonitor')
        logger.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console = logging.StreamHandler(sys.stdout)
        if self.config.quiet:
            console.setLevel(logging.ERROR)
        elif self.config.verbose:
            console.setLevel(logging.DEBUG)
        else:
            console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)
        
        if self.config.log_file:
            file_handler = logging.FileHandler(
                self.config.log_file, 
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    # ==================== СБОР МЕТРИК ====================
    
    def get_timewait_stats(self) -> Dict:
        tw_connections = []
        tw_by_pid = {}
        tw_by_remote = {}
        total_tw = 0
        
        try:
            for conn in psutil.net_connections(kind='tcp'):
                if conn.status == 'TIME_WAIT':
                    total_tw += 1
                    tw_connections.append(conn)
                    if conn.pid:
                        tw_by_pid[conn.pid] = tw_by_pid.get(conn.pid, 0) + 1
                    if conn.raddr:
                        remote_key = f"{conn.raddr.ip}:{conn.raddr.port}"
                        tw_by_remote[remote_key] = tw_by_remote.get(remote_key, 0) + 1
        except Exception as e:
            self.logger.error(f"Ошибка получения TIME_WAIT: {e}")
        
        top_pids = sorted(tw_by_pid.items(), key=lambda x: x[1], reverse=True)[:5]
        top_procs = []
        for pid, count in top_pids:
            try:
                proc = psutil.Process(pid)
                top_procs.append({
                    'pid': pid,
                    'name': proc.name(),
                    'timewait_count': count
                })
            except:
                top_procs.append({
                    'pid': pid,
                    'name': f'PID_{pid}',
                    'timewait_count': count
                })
        
        top_remotes = sorted(tw_by_remote.items(), key=lambda x: x[1], reverse=True)[:5]
        top_remotes = [{'address': addr, 'count': count} for addr, count in top_remotes]
        
        return {
            'total': total_tw,
            'by_pid': top_procs,
            'by_remote': top_remotes,
            'all_connections': tw_connections
        }
    
    def get_memory_stats(self) -> Dict:
        """Сбор статистики памяти с реальными значениями CPU для Windows"""
        processes = []
        total_rss = 0
        
        try:
            # Первый проход: собираем все процессы
            proc_list = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mem = proc.info['memory_info']
                    if mem.rss > 0:
                        proc_list.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'rss_mb': mem.rss / 1024 / 1024,
                            'vms_mb': mem.vms / 1024 / 1024,
                            'proc': proc
                        })
                        total_rss += mem.rss / 1024 / 1024
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not proc_list:
                return {}
            
            # Сортируем по памяти и берём ТОП
            proc_list.sort(key=lambda x: x['rss_mb'], reverse=True)
            top_procs = proc_list[:self.config.top_processes * 2]
            
            # ВАЖНО: Ждём 1 секунду для сбора корректного CPU
            time.sleep(1.0)
            
            # Собираем CPU для ТОП-процессов
            for proc_info in top_procs:
                try:
                    proc = proc_info['proc']
                    # Используем интервал 1 секунду
                    cpu = proc.cpu_percent(interval=1.0)
                    proc_info['cpu'] = cpu
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_info['cpu'] = 0.0
            
            # Сортируем обратно по памяти
            top_procs.sort(key=lambda x: x['rss_mb'], reverse=True)
            top_procs = top_procs[:self.config.top_processes]
            
            # Формируем результат
            top_processes = []
            for p in top_procs:
                cpu_val = p.get('cpu', 0.0)
                # Если CPU = 0.0, пробуем получить ещё раз (для точности)
                if cpu_val == 0.0 and p['rss_mb'] > 50:
                    try:
                        cpu_val = p['proc'].cpu_percent(interval=0.5)
                    except:
                        pass
                
                top_processes.append({
                    'pid': p['pid'],
                    'name': p['name'],
                    'rss_mb': p['rss_mb'],
                    'vms_mb': p['vms_mb'],
                    'cpu': cpu_val
                })
            
            # Проверка порогов
            warnings = []
            for proc in top_processes:
                if proc['rss_mb'] > self.config.mem_threshold_mb:
                    warnings.append(
                        f"🔴 {proc['name']} (PID {proc['pid']}): {proc['rss_mb']:.1f} МБ, CPU: {proc['cpu']:.1f}%% (КРИТИЧНО)"
                    )
                elif proc['rss_mb'] > self.config.mem_warning_mb:
                    warnings.append(
                        f"🟡 {proc['name']} (PID {proc['pid']}): {proc['rss_mb']:.1f} МБ, CPU: {proc['cpu']:.1f}%% (ПРЕДУПРЕЖДЕНИЕ)"
                    )
            
            # Системная память
            try:
                mem_total = psutil.virtual_memory()
                swap = psutil.swap_memory()
                system_memory = {
                    'total_gb': mem_total.total / 1024 / 1024 / 1024,
                    'available_gb': mem_total.available / 1024 / 1024 / 1024,
                    'used_percent': mem_total.percent,
                    'swap_used_gb': swap.used / 1024 / 1024 / 1024 if swap else 0
                }
            except:
                system_memory = {}
            
            return {
                'top_processes': top_processes,
                'system': system_memory,
                'warnings': warnings,
                'total_rss_gb': total_rss / 1024
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения памяти: {e}")
            return {}
    
    def get_cpu_stats(self) -> Dict:
        """Сбор статистики CPU"""
        try:
            cpu_per_core = psutil.cpu_percent(interval=0.5, percpu=True)
            cpu_avg = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0
            
            try:
                load_avg = psutil.getloadavg()
            except AttributeError:
                load_avg = (cpu_avg, cpu_avg, cpu_avg)
            
            try:
                ctx_switches = psutil.cpu_stats().ctx_switches
            except:
                ctx_switches = 0
            
            return {
                'avg_percent': cpu_avg,
                'per_core': cpu_per_core,
                'load_avg_1min': load_avg[0] if load_avg else cpu_avg,
                'load_avg_5min': load_avg[1] if len(load_avg) > 1 else cpu_avg,
                'load_avg_15min': load_avg[2] if len(load_avg) > 2 else cpu_avg,
                'ctx_switches': ctx_switches,
                'status': '🔴 КРИТИЧНО' if cpu_avg > self.config.cpu_threshold else \
                         '🟡 ПРЕДУПРЕЖДЕНИЕ' if cpu_avg > self.config.cpu_warning else '🟢 НОРМА'
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения CPU: {e}")
            return {}
    
    def get_network_stats(self) -> Dict:
        """Сбор сетевой статистики"""
        try:
            net_io = psutil.net_io_counters()
            current_time = time.time()
            
            if self.prev_net and self.prev_time:
                time_delta = current_time - self.prev_time
                if time_delta > 0:
                    bytes_sent = net_io.bytes_sent - self.prev_net.bytes_sent
                    bytes_recv = net_io.bytes_recv - self.prev_net.bytes_recv
                    packets_sent = net_io.packets_sent - self.prev_net.packets_sent
                    packets_recv = net_io.packets_recv - self.prev_net.packets_recv
                    
                    up_mbps = (bytes_sent * 8) / (time_delta * 1024 * 1024)
                    down_mbps = (bytes_recv * 8) / (time_delta * 1024 * 1024)
                    pps = (packets_sent + packets_recv) / time_delta
                    
                    err_in = net_io.errin - self.prev_net.errin
                    err_out = net_io.errout - self.prev_net.errout
                    drop_in = net_io.dropin - self.prev_net.dropin
                    drop_out = net_io.dropout - self.prev_net.dropout
                else:
                    up_mbps = down_mbps = pps = 0
                    err_in = err_out = drop_in = drop_out = 0
            else:
                up_mbps = down_mbps = pps = 0
                err_in = err_out = drop_in = drop_out = 0
            
            self.prev_net = net_io
            self.prev_time = current_time
            
            status = '🔴 КРИТИЧНО' if up_mbps > self.config.net_threshold or down_mbps > self.config.net_threshold else \
                     '🟡 ПРЕДУПРЕЖДЕНИЕ' if up_mbps > self.config.net_warning or down_mbps > self.config.net_warning else '🟢 НОРМА'
            
            return {
                'up_mbps': up_mbps,
                'down_mbps': down_mbps,
                'pps': pps,
                'err_in': err_in,
                'err_out': err_out,
                'drop_in': drop_in,
                'drop_out': drop_out,
                'total_errors': err_in + err_out,
                'total_drops': drop_in + drop_out,
                'status': status
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения сети: {e}")
            return {}
    
    def get_tcp_stats(self) -> Dict:
        """Сбор общей статистики TCP"""
        try:
            stats = {'ESTABLISHED': 0, 'TIME_WAIT': 0, 'CLOSE_WAIT': 0, 'OTHER': 0}
            for conn in psutil.net_connections(kind='tcp'):
                if conn.status == 'ESTABLISHED':
                    stats['ESTABLISHED'] += 1
                elif conn.status == 'TIME_WAIT':
                    stats['TIME_WAIT'] += 1
                elif conn.status == 'CLOSE_WAIT':
                    stats['CLOSE_WAIT'] += 1
                else:
                    stats['OTHER'] += 1
            return stats
        except:
            return {}
    
    # ==================== АНАЛИЗ И ДИАГНОСТИКА ====================
    
    def _can_alert(self, issue_key: str, current_time: float) -> bool:
        last_time = self._last_alert_time.get(issue_key, 0)
        if current_time - last_time > self._alert_cooldown:
            self._last_alert_time[issue_key] = current_time
            return True
        return False
    
    def _get_max_memory_growth(self) -> Optional[float]:
        max_growth = 0
        for proc_name, trend in self.trends['memory'].items():
            if isinstance(trend, TrendAnalyzer):
                trend_val = trend.get_trend()
                if trend_val and trend_val > max_growth:
                    max_growth = trend_val
        return max_growth if max_growth > 0 else None
    
    def analyze_problems(self, data: Dict) -> List[str]:
        issues = []
        current_time = time.time()
        
        tw_data = data.get('timewait', {})
        mem_data = data.get('memory', {})
        cpu_data = data.get('cpu', {})
        net_data = data.get('network', {})
        
        tw_count = tw_data.get('total', 0)
        cpu_load = cpu_data.get('avg_percent', 0)
        errors = net_data.get('total_errors', 0)
        mem_system = mem_data.get('system', {})
        
        # SWAP
        swap_used = mem_system.get('swap_used_gb', 0)
        if swap_used > 1.0:
            if self._can_alert('swap', current_time):
                issues.append(
                    f"🔄 Используется SWAP: {swap_used:.1f} ГБ -> нехватка RAM. "
                    f"Рекомендуется добавить память или оптимизировать приложения"
                )
        
        # DDoS
        top_remotes = tw_data.get('by_remote', [])
        if top_remotes:
            top_remote = top_remotes[0]
            remote_count = top_remote.get('count', 0)
            remote_addr = top_remote.get('address', 'unknown')
            
            is_ddos = (
                remote_count > 100 or
                (remote_count > 50 and tw_count > 200 and remote_count > tw_count * 0.3)
            )
            if is_ddos:
                if self._can_alert(f'ddos_{remote_addr}', current_time):
                    issues.append(
                        f"🚨 ПОДОЗРЕНИЕ НА DDoS: хост {remote_addr} создал "
                        f"{remote_count} TIME_WAIT соединений ({remote_count/tw_count*100:.1f}%% от всех)"
                    )
        
        # High CPU
        if cpu_load > self.config.cpu_threshold:
            if self._can_alert('high_cpu', current_time):
                issues.append(
                    f"🔥 ВЫСОКАЯ НАГРУЗКА CPU: {cpu_load:.1f}%% (порог: {self.config.cpu_threshold}%%)"
                )
        
        # Memory leak
        mem_growth = self._get_max_memory_growth()
        if mem_growth and mem_growth > 20:
            if self._can_alert('memory_leak', current_time):
                top_proc = mem_data.get('top_processes', [{}])[0]
                proc_name = top_proc.get('name', 'unknown')
                proc_pid = top_proc.get('pid', 0)
                issues.append(
                    f"💾 ПОДОЗРЕНИЕ НА УТЕЧКУ ПАМЯТИ: {proc_name} (PID {proc_pid}) "
                    f"вырос на {mem_growth:.1f}%% за {self.config.trend_window} сек"
                )
        
        # Network errors
        if errors > 1000:
            if self._can_alert('network_errors', current_time):
                issues.append(
                    f"🔌 ПРОБЛЕМЫ С СЕТЬЮ: {errors} ошибок на NIC. "
                    f"Проверьте кабель, драйвер или коммутатор"
                )
        
        # TIME_WAIT high
        if tw_count > self.config.tw_threshold:
            if self._can_alert('timewait_high', current_time):
                top_procs = tw_data.get('by_pid', [])
                if top_procs and top_procs[0].get('timewait_count', 0) > tw_count * 0.5:
                    proc = top_procs[0]
                    issues.append(
                        f"⚠️ ИСЧЕРПАНИЕ ПОРТОВ: {tw_count} TIME_WAIT, "
                        f"{proc['timewait_count']} из них созданы процессом {proc['name']} (PID {proc['pid']})"
                    )
                else:
                    issues.append(
                        f"⚠️ ИСЧЕРПАНИЕ ПОРТОВ: TIME_WAIT = {tw_count} "
                        f"(порог: {self.config.tw_threshold})"
                    )
        
        # System memory high
        mem_used_percent = mem_system.get('used_percent', 0)
        if mem_used_percent > 90:
            if self._can_alert('system_memory_high', current_time):
                issues.append(
                    f"💾 КРИТИЧЕСКАЯ НЕХВАТКА ПАМЯТИ: использовано {mem_used_percent:.1f}%%"
                )
        
        # High context switches
        ctx_switches = cpu_data.get('ctx_switches', 0)
        if ctx_switches > 1000000000:
            if self._can_alert('high_context_switches', current_time):
                issues.append(
                    f"⚠️ АНОМАЛЬНО МНОГО КОНТЕКСТНЫХ ПЕРЕКЛЮЧЕНИЙ: {ctx_switches:,}. "
                    f"Возможны проблемы с драйверами или антивирусом"
                )
        
        return issues
    
    # ==================== СОХРАНЕНИЕ СНАПШОТА ====================
    
    def save_snapshot(self, data: Dict):
        if not self.config.snapshot_dir:
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(self.config.snapshot_dir, f'snapshot_{timestamp}.json')
        
        try:
            clean_data = {
                'timestamp': datetime.now().isoformat(),
                'timewait': {
                    'total': data.get('timewait', {}).get('total', 0),
                    'top_remote': data.get('timewait', {}).get('by_remote', [])[:3],
                    'top_pids': data.get('timewait', {}).get('by_pid', [])[:3]
                },
                'memory': {
                    'top_processes': data.get('memory', {}).get('top_processes', [])[:3],
                    'system': data.get('memory', {}).get('system', {})
                },
                'cpu': {
                    'avg_percent': data.get('cpu', {}).get('avg_percent', 0),
                    'load_avg': data.get('cpu', {}).get('load_avg_1min', 0),
                    'ctx_switches': data.get('cpu', {}).get('ctx_switches', 0)
                },
                'network': {
                    'up_mbps': data.get('network', {}).get('up_mbps', 0),
                    'down_mbps': data.get('network', {}).get('down_mbps', 0),
                    'pps': data.get('network', {}).get('pps', 0),
                    'total_errors': data.get('network', {}).get('total_errors', 0)
                },
                'issues': data.get('issues', [])
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Ошибка сохранения снапшота: {e}")
    
    # ==================== ВЫВОД ====================
    
    def print_verbose(self, data: Dict):
        separator = "=" * 70
        self.logger.info(separator)
        
        issues = data.get('issues', [])
        if issues:
            status = "🔴 КРИТИЧЕСКИЙ" if any("КРИТИЧЕСКАЯ" in str(issue) for issue in issues) else "🟡 ПРЕДУПРЕЖДЕНИЕ"
        else:
            status = "🟢 НОРМАЛЬНЫЙ"
        
        self.logger.info(f"📊 СТАТУС: {status}")
        
        # TIME_WAIT
        tw = data.get('timewait', {})
        self.logger.info(f"📈 TIME_WAIT: {tw.get('total', 0)}")
        
        tw_trend = self.trends['timewait'].get_trend()
        if tw_trend is not None:
            arrow = "⬆️" if tw_trend > 0 else "⬇️" if tw_trend < 0 else "➡️"
            self.logger.info(f"   Тренд: {arrow} {tw_trend:.1f}%% за {self.config.trend_window} сек")
        
        top_remotes = tw.get('by_remote', [])
        if top_remotes:
            self.logger.info("   🎯 ТОП-5 удалённых хостов в TIME_WAIT:")
            for remote in top_remotes:
                self.logger.info(f"      {remote['address']}: {remote['count']} соединений")
        
        # Memory
        mem = data.get('memory', {})
        self.logger.info(f"🧠 ПАМЯТЬ:")
        mem_system = mem.get('system', {})
        if mem_system:
            self.logger.info(f"   Система: {mem_system.get('used_percent', 0):.1f}%% использовано "
                           f"({mem_system.get('available_gb', 0):.1f} ГБ свободно)")
            if mem_system.get('swap_used_gb', 0) > 0:
                self.logger.info(f"   SWAP: {mem_system.get('swap_used_gb', 0):.1f} ГБ использовано")
        
        top_mem = mem.get('top_processes', [])
        if top_mem:
            self.logger.info("   📊 ТОП-5 процессов по памяти (RSS):")
            for proc in top_mem:
                mem_status = ""
                if proc['rss_mb'] > self.config.mem_threshold_mb:
                    mem_status = "🔴 КРИТИЧНО"
                elif proc['rss_mb'] > self.config.mem_warning_mb:
                    mem_status = "🟡 ПРЕДУПРЕЖДЕНИЕ"
                self.logger.info(f"      {proc['name']} (PID {proc['pid']}): "
                               f"{proc['rss_mb']:.1f} МБ, CPU: {proc['cpu']:.1f}%% {mem_status}")
        
        # CPU
        cpu = data.get('cpu', {})
        self.logger.info(f"💻 CPU:")
        self.logger.info(f"   Средняя нагрузка: {cpu.get('avg_percent', 0):.1f}%% {cpu.get('status', '')}")
        if cpu.get('per_core'):
            self.logger.info(f"   По ядрам: {', '.join([f'{c:.1f}%%' for c in cpu.get('per_core', [])])}")
        
        ctx_switches = cpu.get('ctx_switches', 0)
        if ctx_switches > 0:
            self.logger.info(f"   Контекстных переключений: {ctx_switches:,}")
        
        # Network
        net = data.get('network', {})
        self.logger.info(f"🌐 СЕТЬ {net.get('status', '')}:")
        self.logger.info(f"   📤 Отправка: {net.get('up_mbps', 0):.1f} Мбит/с")
        self.logger.info(f"   📥 Получение: {net.get('down_mbps', 0):.1f} Мбит/с")
        self.logger.info(f"   📦 Пакетов/с: {net.get('pps', 0):.0f}")
        
        if net.get('total_errors', 0) > 0:
            self.logger.warning(f"   ❌ Ошибки сети: {net.get('total_errors', 0)}")
        if net.get('total_drops', 0) > 0:
            self.logger.warning(f"   📦 Потерянные пакеты: {net.get('total_drops', 0)}")
        
        # Диагностика
        if issues:
            self.logger.info("🔍 ДИАГНОСТИКА:")
            for issue in issues:
                self.logger.info(f"   {issue}")
        
        # TCP
        tcp = data.get('tcp', {})
        if tcp:
            self.logger.info(f"🔌 TCP СОЕДИНЕНИЯ:")
            self.logger.info(f"   ESTABLISHED: {tcp.get('ESTABLISHED', 0)}")
            self.logger.info(f"   TIME_WAIT: {tcp.get('TIME_WAIT', 0)}")
            self.logger.info(f"   CLOSE_WAIT: {tcp.get('CLOSE_WAIT', 0)}")
            self.logger.info(f"   OTHER: {tcp.get('OTHER', 0)}")
        
        self.logger.info(separator)
    
    def print_quiet(self, data: Dict):
        issues = data.get('issues', [])
        
        if issues:
            issue_hash = hash(str(sorted(issues)))
            last_hash = getattr(self, '_last_issue_hash', None)
            last_issue_time = getattr(self, '_last_issue_time', 0)
            
            if issue_hash != last_hash or time.time() - last_issue_time > 60:
                if issue_hash != last_hash:
                    self.logger.warning("🚨 ОБНАРУЖЕНЫ НОВЫЕ ПРОБЛЕМЫ:")
                else:
                    self.logger.warning("🚨 ПРОБЛЕМЫ СОХРАНЯЮТСЯ (повтор через 60 сек):")
                
                for issue in issues:
                    self.logger.warning(f"   {issue}")
                self._last_issue_hash = issue_hash
                self._last_issue_time = time.time()
        
        if not hasattr(self, '_status_counter'):
            self._status_counter = 0
        self._status_counter += 1
        
        status_interval = max(1, int(self.config.status_interval / self.config.interval))
        if self._status_counter >= status_interval:
            self._status_counter = 0
            tw = data.get('timewait', {}).get('total', 0)
            net = data.get('network', {})
            cpu = data.get('cpu', {}).get('avg_percent', 0)
            mem = data.get('memory', {}).get('system', {}).get('used_percent', 0)
            
            self.logger.info(f"📊 Статус: TIME_WAIT={tw}, "
                           f"Сеть=↑{net.get('up_mbps', 0):.1f}↓{net.get('down_mbps', 0):.1f} Мбит/с, "
                           f"CPU={cpu:.1f}%%, MEM={mem:.1f}%%")
    
    # ==================== ОСНОВНОЙ ЦИКЛ ====================
    
    def run(self):
        self.logger.info("=" * 70)
        self.logger.info("🛰️  МОНИТОР TIME_WAIT PRO + ПАМЯТЬ + CPU + ПРОЦЕССЫ")
        self.logger.info(f"📌 TIME_WAIT: предупреждение {self.config.tw_warning}, критично {self.config.tw_threshold}")
        self.logger.info(f"🌐 СЕТЬ: предупреждение {self.config.net_warning} Мбит/с, критично {self.config.net_threshold} Мбит/с")
        self.logger.info(f"🧠 ПАМЯТЬ: предупреждение {self.config.mem_warning_mb} МБ, критично {self.config.mem_threshold_mb} МБ")
        self.logger.info(f"💻 CPU: предупреждение {self.config.cpu_warning}%%, критично {self.config.cpu_threshold}%%")
        self.logger.info(f"ℹ️  Режим: {'ВЕРБОЗНЫЙ' if self.config.verbose else 'ТИХИЙ'}")
        self.logger.info(f"⏱️  Интервал: {self.config.interval} сек")
        self.logger.info("=" * 70)
        
        try:
            while True:
                tw_stats = self.get_timewait_stats()
                mem_stats = self.get_memory_stats()
                cpu_stats = self.get_cpu_stats()
                net_stats = self.get_network_stats()
                tcp_stats = self.get_tcp_stats()
                
                self.trends['timewait'].add_value(tw_stats.get('total', 0))
                self.trends['cpu'].add_value(cpu_stats.get('avg_percent', 0))
                self.trends['net_up'].add_value(net_stats.get('up_mbps', 0))
                self.trends['net_down'].add_value(net_stats.get('down_mbps', 0))
                self.trends['pps'].add_value(net_stats.get('pps', 0))
                self.trends['errors'].add_value(net_stats.get('total_errors', 0))
                
                for proc in mem_stats.get('top_processes', []):
                    proc_name = f"{proc['name']}_PID{proc['pid']}"
                    if proc_name not in self.trends['memory']:
                        self.trends['memory'][proc_name] = TrendAnalyzer(self.config.trend_window)
                    self.trends['memory'][proc_name].add_value(proc['rss_mb'])
                
                data = {
                    'timewait': tw_stats,
                    'memory': mem_stats,
                    'cpu': cpu_stats,
                    'network': net_stats,
                    'tcp': tcp_stats
                }
                issues = self.analyze_problems(data)
                data['issues'] = issues
                
                if issues:
                    self.save_snapshot(data)
                
                if self.config.verbose:
                    self.print_verbose(data)
                else:
                    self.print_quiet(data)
                
                # Корректируем задержку, чтобы не накапливать sleep
                # (мы уже сделали паузу 1 секунду внутри get_memory_stats)
                time.sleep(max(0, self.config.interval - 1.0))
                
        except KeyboardInterrupt:
            self.logger.info("\n🛑 Монитор остановлен пользователем")
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка: {e}")
            raise

# ==================== ТОЧКА ВХОДА ====================

def main():
    parser = argparse.ArgumentParser(
        description='Network Monitor PRO - расширенный мониторинг TIME_WAIT, памяти, CPU и процессов'
    )
    
    parser.add_argument('-t', '--threshold', type=int, default=1000,
                       help='Критический порог TIME_WAIT (по умолчанию: 1000)')
    parser.add_argument('-w', '--warning', type=int, default=500,
                       help='Предупредительный порог TIME_WAIT (по умолчанию: 500)')
    
    parser.add_argument('-n', '--network-threshold', type=int, default=950,
                       help='Критическая скорость сети в Мбит/с (по умолчанию: 950)')
    parser.add_argument('-nw', '--network-warning', type=int, default=700,
                       help='Предупредительная скорость сети в Мбит/с (по умолчанию: 700)')
    
    parser.add_argument('-m', '--mem-threshold', type=int, default=1024,
                       help='Критический размер RSS процесса в МБ (по умолчанию: 1024)')
    parser.add_argument('-mw', '--mem-warning', type=int, default=512,
                       help='Предупредительный размер RSS процесса в МБ (по умолчанию: 512)')
    
    parser.add_argument('-c', '--cpu-threshold', type=int, default=80,
                       help='Критическая загрузка CPU в %%%% (по умолчанию: 80)')
    parser.add_argument('-cw', '--cpu-warning', type=int, default=60,
                       help='Предупредительная загрузка CPU в %%%% (по умолчанию: 60)')
    
    parser.add_argument('-i', '--interval', type=float, default=2.0,
                       help='Интервал проверки в секундах (по умолчанию: 2.0)')
    parser.add_argument('-l', '--log-file', type=str, default=None,
                       help='Путь к файлу для сохранения лога')
    parser.add_argument('-s', '--snapshot-dir', type=str, default='snapshots',
                       help='Директория для сохранения снапшотов (по умолчанию: snapshots)')
    parser.add_argument('--no-snapshots', action='store_true',
                       help='Отключить сохранение снапшотов')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Вербозный режим (показывать всё)')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Максимально тихий режим')
    
    parser.add_argument('--top', type=int, default=5,
                       help='Количество ТОП-процессов для отображения (по умолчанию: 5)')
    parser.add_argument('--trend-window', type=int, default=60,
                       help='Размер окна для трендов в секундах (по умолчанию: 60)')
    parser.add_argument('--alert-cooldown', type=int, default=60,
                       help='Интервал между повторными предупреждениями в секундах (по умолчанию: 60)')
    parser.add_argument('--status-interval', type=int, default=60,
                       help='Интервал вывода статуса в тихом режиме в секундах (по умолчанию: 60)')
    
    args = parser.parse_args()
    
    config = Config(
        tw_threshold=args.threshold,
        tw_warning=args.warning,
        net_threshold=args.network_threshold,
        net_warning=args.network_warning,
        mem_threshold_mb=args.mem_threshold,
        mem_warning_mb=args.mem_warning,
        cpu_threshold=args.cpu_threshold,
        cpu_warning=args.cpu_warning,
        interval=args.interval,
        log_file=args.log_file,
        snapshot_dir=None if args.no_snapshots else args.snapshot_dir,
        verbose=args.verbose,
        quiet=args.quiet,
        top_processes=args.top,
        trend_window=args.trend_window,
        alert_cooldown=args.alert_cooldown,
        status_interval=args.status_interval
    )
    
    monitor = NetworkMonitor(config)
    monitor.run()

if __name__ == '__main__':
    main()