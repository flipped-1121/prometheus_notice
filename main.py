# -*- encoding=utf-8 -*-
"""
    @Author: Kang
    @Modifier: 
    @Date: 2024/11/11 12:31
    @Description: Prometheus metrics monitoring and notification system
"""
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
import yaml

import requests
import pandas as pd
from jinja2 import Environment, FileSystemLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class EmailConfig:
    """Email configuration settings"""
    smtp_server: str
    smtp_port: int
    from_name: str
    username: str
    password: str
    subject: str
    recipients: List[str]


class EmailSender:
    """Handles email sending functionality"""
    def __init__(self, config: EmailConfig):
        self.config = config

    def send(self, subject: str, body: str, html: bool = False, attachments: Optional[List[Path]] = None) -> bool:
        """Send an email with optional HTML content and attachments"""
        try:
            message = self._create_message(subject, body, html)
            self._add_attachments(message, attachments)
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _create_message(self, subject: str, body: str, html: bool) -> MIMEMultipart:
        message = MIMEMultipart()
        message["From"] = f"{self.config.from_name} <{self.config.username}>"
        message["To"] = ", ".join(self.config.recipients)
        message["Subject"] = subject
        
        content_type = "html" if html else "plain"
        message.attach(MIMEText(body, content_type))
        return message

    def _add_attachments(self, message: MIMEMultipart, attachments: Optional[List[Path]]) -> None:
        if not attachments:
            return
            
        for file_path in attachments:
            try:
                with open(file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={file_path.name}"
                    )
                    message.attach(part)
            except Exception as e:
                logger.error(f"Error attaching file {file_path}: {e}")

    def _send_message(self, message: MIMEMultipart) -> bool:
        try:
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                server.starttls()
                server.login(self.config.username, self.config.password)
                server.sendmail(
                    self.config.username,
                    self.config.recipients,
                    message.as_string()
                )
            logger.info("Email sent successfully!")
            return True
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False


class PrometheusMetrics:
    """Collects and processes Prometheus metrics"""
    def __init__(self, url: str):
        self.url = url
        self.node_list: List[str] = []
        self.disk_list: List[Dict[str, Any]] = []
        self.cpu_list: List[Dict[str, Any]] = []
        self.mem_list: List[Dict[str, Any]] = []
        self.net_list: List[Dict[str, Any]] = []
        self.jinja_env = Environment(loader=FileSystemLoader('templates'))

    def _query_prometheus(self, query: str) -> Dict:
        """Make a query to Prometheus API"""
        try:
            response = requests.get(self.url, params={"query": query}, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to query Prometheus: {e}")
            return {"data": {"result": []}}

    def get_node_metrics(self) -> None:
        """Get list of nodes from Prometheus"""
        query = 'node_uname_info{vendor=~"",account=~"",group=~"()",name=~"()",name=~".*.*"} - 0'
        result = self._query_prometheus(query)
        self.node_list = [node["metric"]["instance"] for node in result["data"]["result"]]

    def get_disk_metrics(self, instance: str) -> None:
        """Get disk metrics for a specific node"""
        query_size = f'node_filesystem_size_bytes{{instance=~"{instance}",fstype=~"ext.*|xfs|nfs",mountpoint !~".*pod.*"}}'
        query_free = f'node_filesystem_free_bytes{{instance=~"{instance}",fstype=~"ext.*|xfs|nfs",mountpoint !~".*pod.*"}}'
        
        result_size = self._query_prometheus(query_size)
        result_free = self._query_prometheus(query_free)
        
        for size, free in zip(result_size["data"]["result"], result_free["data"]["result"]):
            size_value = float(size["value"][1])
            free_value = float(free["value"][1])
            used_value = size_value - free_value
            usage_percent = (used_value / size_value * 100) if size_value > 0 else 0
            
            self.disk_list.append({
                "device": size["metric"]["device"],
                "usage_percent": usage_percent,
                "instance": instance,
                "mount_point": size["metric"]["mountpoint"],
                "size": self._format_bytes(size_value),
                "free": self._format_bytes(free_value),
                "used": self._format_bytes(used_value)
            })

    def get_cpu_metrics(self, instance: str) -> None:
        """Get CPU metrics for a specific node"""
        query_usage_percent = f'(1 - avg(irate(node_cpu_seconds_total{{instance=~"{instance}",mode=~"idle"}}[3m])) by (instance)) * 100'
        query_core_num = f'count(node_cpu_seconds_total{{instance=~"{instance}",mode="system"}}) by (instance)'
        
        result_usage_percent = self._query_prometheus(query_usage_percent)
        result_core_num = self._query_prometheus(query_core_num)
        
        for usage_percent, core_num in zip(result_usage_percent["data"]["result"], result_core_num["data"]["result"]):
            usage_value = float(usage_percent["value"][1])
            core_num_value = float(core_num["value"][1])
            self.cpu_list.append({
                "instance": instance,
                "usage_percent": usage_value,
                "core_num": core_num_value
            })


    def get_mem_metrics(self, instance: str) -> None:
        """Get memory metrics for a specific node"""
        query_total = f'node_memory_MemTotal_bytes{{instance=~"{instance}"}}'
        query_avail = f'node_memory_MemAvailable_bytes{{instance=~"{instance}"}}'
        
        result_total = self._query_prometheus(query_total)
        result_avail = self._query_prometheus(query_avail)
        
        for total, avail in zip(result_total["data"]["result"], result_avail["data"]["result"]):
            total_value = float(total["value"][1])
            used_value = total_value - float(avail["value"][1])
            usage_percent = (used_value / total_value * 100) if total_value > 0 else 0
            
            self.mem_list.append({
                "instance": instance,
                "total": self._format_bytes(total_value),
                "used": self._format_bytes(used_value),
                "usage_percent": usage_percent
            })

    def get_net_metrics(self, instance: str) -> None:
        """Get network metrics for a specific node"""
        query_rx = f'max(irate(node_network_receive_bytes_total{{instance=~"{instance}",device=~"eth.*|ens.*"}}[3m])*8) by (instance)'
        query_tx = f'max(irate(node_network_transmit_bytes_total{{instance=~"{instance}",device=~"eth.*|ens.*"}}[3m])*8) by (instance)'
        
        result_rx = self._query_prometheus(query_rx)
        result_tx = self._query_prometheus(query_tx)
        
        for rx, tx in zip(result_rx["data"]["result"], result_tx["data"]["result"]):
            self.net_list.append({
                "instance": instance,
                "download": self._format_bits_per_second(float(rx["value"][1])),
                "upload": self._format_bits_per_second(float(tx["value"][1]))
            })

    @staticmethod
    def _format_bytes(bytes_value: float) -> str:
        """Format bytes to human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.2f} PB"

    @staticmethod
    def _format_bits_per_second(bps: float) -> str:
        """Format bits per second to human-readable format"""
        for unit in ['bps', 'Kbps', 'Mbps', 'Gbps']:
            if bps < 1000:
                return f"{bps:.2f} {unit}"
            bps /= 1000
        return f"{bps:.2f} Tbps"

    def generate_html_report(self) -> str:
        """Generate HTML report using template"""
        template = self.jinja_env.get_template('prometheus_report_zh.html')
        return template.render(
            nodes=self.node_list,
            disks=self.disk_list,
            cpus=self.cpu_list,
            mems=self.mem_list,
            nets=self.net_list,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
    
    def generate_excel_report(self, file_path: Path) -> None:
        """Generate Excel report file"""
        # Prepare data for each metric type
        disk_df = pd.DataFrame(self.disk_list)
        cpu_df = pd.DataFrame(self.cpu_list) 
        mem_df = pd.DataFrame(self.mem_list)
        net_df = pd.DataFrame(self.net_list)
        
        # Create Excel writer object
        with pd.ExcelWriter(file_path) as writer:
            # Write each DataFrame to a different sheet
            disk_df.to_excel(writer, sheet_name='Disk Usage', index=False)
            cpu_df.to_excel(writer, sheet_name='CPU Usage', index=False)
            mem_df.to_excel(writer, sheet_name='Memory Usage', index=False)
            net_df.to_excel(writer, sheet_name='Network Usage', index=False)
            
        logger.info(f"Excel report generated successfully at {file_path}")
        

class PrometheusNotice:
    """Main class for Prometheus monitoring and notification"""
    def __init__(self, config: EmailConfig, prometheus_url: str):
        self.email_sender = EmailSender(config)
        self.prometheus_metrics = PrometheusMetrics(prometheus_url)

    def run(self) -> None:
        """Execute the monitoring and notification process"""
        try:
            self.prometheus_metrics.get_node_metrics()
            for node in self.prometheus_metrics.node_list:
                self.prometheus_metrics.get_disk_metrics(node)
                self.prometheus_metrics.get_cpu_metrics(node)
                self.prometheus_metrics.get_mem_metrics(node)
                self.prometheus_metrics.get_net_metrics(node)

            excel_report_path = Path('report.xlsx')
            self.prometheus_metrics.generate_excel_report(excel_report_path)

            html_report = self.prometheus_metrics.generate_html_report()
            self.email_sender.send(
                subject=self.email_sender.config.subject,
                body=html_report,
                html=True,
                attachments=[excel_report_path]
            )
        except Exception as e:
            logger.error(f"Failed to run monitoring: {e}")


if __name__ == '__main__':
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    email_config = EmailConfig(**config['email'])
    prometheus_url = config['prometheus']['url']

    prometheus_notice = PrometheusNotice(email_config, prometheus_url)
    prometheus_notice.run()