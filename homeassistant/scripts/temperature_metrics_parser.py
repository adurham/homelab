#!/usr/bin/env python3
"""
Temperature Metrics Parser for Grafana Integration
Parses structured log entries and creates metrics for Grafana visualization
"""

import json
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

class TemperatureMetricsParser:
    def __init__(self):
        self.metrics = {
            'temperature_drift': {},
            'temperature_variance': {},
            'efficiency_scores': {},
            'occupancy_metrics': {}
        }
    
    def parse_log_line(self, log_line: str) -> Optional[Dict[str, Any]]:
        """Parse a single log line and extract structured metrics"""
        
        # Extract JSON from log messages
        if 'TEMPERATURE_METRICS:' in log_line:
            return self._parse_temperature_metrics(log_line)
        elif 'TEMPERATURE_VARIANCE_METRICS:' in log_line:
            return self._parse_variance_metrics(log_line)
        elif 'EFFICIENCY_METRICS:' in log_line:
            return self._parse_efficiency_metrics(log_line)
        
        return None
    
    def _parse_temperature_metrics(self, log_line: str) -> Dict[str, Any]:
        """Parse temperature drift metrics"""
        try:
            # Extract JSON from log line
            json_start = log_line.find('{')
            json_end = log_line.rfind('}') + 1
            json_str = log_line[json_start:json_end]
            
            data = json.loads(json_str)
            
            metrics = {
                'timestamp': data.get('timestamp'),
                'ecobee_setpoint': data.get('ecobee_setpoint'),
                'ecobee_mode': data.get('ecobee_mode'),
                'rooms': {}
            }
            
            # Process occupied rooms
            for room_name, room_data in data.get('occupied_rooms', {}).items():
                if room_data.get('temperature') is not None:
                    metrics['rooms'][f'{room_name}_occupied'] = {
                        'temperature': room_data['temperature'],
                        'drift_from_setpoint': room_data.get('drift_from_setpoint', 0),
                        'vent_position': room_data.get('vent_position', 0),
                        'occupancy': room_data.get('occupancy', 'off'),
                        'room_type': 'occupied'
                    }
            
            # Process unoccupied rooms
            for room_name, room_data in data.get('unoccupied_rooms', {}).items():
                if room_data.get('temperature') is not None:
                    metrics['rooms'][f'{room_name}_unoccupied'] = {
                        'temperature': room_data['temperature'],
                        'drift_from_setpoint': room_data.get('drift_from_setpoint', 0),
                        'vent_position': room_data.get('vent_position', 0),
                        'occupancy': room_data.get('occupancy', 'off'),
                        'room_type': 'unoccupied'
                    }
            
            return {'type': 'temperature_metrics', 'data': metrics}
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error parsing temperature metrics: {e}")
            return None
    
    def _parse_variance_metrics(self, log_line: str) -> Dict[str, Any]:
        """Parse temperature variance metrics"""
        try:
            json_start = log_line.find('{')
            json_end = log_line.rfind('}') + 1
            json_str = log_line[json_start:json_end]
            
            data = json.loads(json_str)
            
            metrics = {
                'timestamp': data.get('timestamp'),
                'occupied_room_temperatures': [t for t in data.get('occupied_room_temperatures', []) if t is not None],
                'unoccupied_room_temperatures': [t for t in data.get('unoccupied_room_temperatures', []) if t is not None],
                'occupied_rooms_count': data.get('occupied_rooms_count', 0),
                'unoccupied_rooms_count': data.get('unoccupied_rooms_count', 0)
            }
            
            # Calculate variance statistics
            if metrics['occupied_room_temperatures']:
                metrics['occupied_variance'] = max(metrics['occupied_room_temperatures']) - min(metrics['occupied_room_temperatures'])
                metrics['occupied_mean'] = sum(metrics['occupied_room_temperatures']) / len(metrics['occupied_room_temperatures'])
            
            if metrics['unoccupied_room_temperatures']:
                metrics['unoccupied_variance'] = max(metrics['unoccupied_room_temperatures']) - min(metrics['unoccupied_room_temperatures'])
                metrics['unoccupied_mean'] = sum(metrics['unoccupied_room_temperatures']) / len(metrics['unoccupied_room_temperatures'])
            
            return {'type': 'variance_metrics', 'data': metrics}
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error parsing variance metrics: {e}")
            return None
    
    def _parse_efficiency_metrics(self, log_line: str) -> Dict[str, Any]:
        """Parse efficiency score metrics"""
        try:
            json_start = log_line.find('{')
            json_end = log_line.rfind('}') + 1
            json_str = log_line[json_start:json_end]
            
            data = json.loads(json_str)
            
            metrics = {
                'timestamp': data.get('timestamp'),
                'temperature_efficiency': data.get('temperature_efficiency', {}),
                'occupancy_efficiency': data.get('occupancy_efficiency', {})
            }
            
            return {'type': 'efficiency_metrics', 'data': metrics}
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error parsing efficiency metrics: {e}")
            return None
    
    def generate_grafana_metrics(self, parsed_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate Grafana-ready metrics from parsed data"""
        
        grafana_metrics = {
            'temperature_drift': [],
            'temperature_variance': [],
            'efficiency_scores': [],
            'occupancy_patterns': []
        }
        
        for entry in parsed_data:
            if not entry:
                continue
                
            entry_type = entry.get('type')
            data = entry.get('data', {})
            
            if entry_type == 'temperature_metrics':
                # Process temperature drift metrics
                timestamp = data.get('timestamp')
                ecobee_setpoint = data.get('ecobee_setpoint')
                
                for room_name, room_data in data.get('rooms', {}).items():
                    grafana_metrics['temperature_drift'].append({
                        'timestamp': timestamp,
                        'room': room_name,
                        'temperature': room_data.get('temperature'),
                        'drift_from_setpoint': room_data.get('drift_from_setpoint'),
                        'vent_position': room_data.get('vent_position'),
                        'occupancy': room_data.get('occupancy'),
                        'room_type': room_data.get('room_type'),
                        'ecobee_setpoint': ecobee_setpoint
                    })
            
            elif entry_type == 'variance_metrics':
                # Process variance metrics
                timestamp = data.get('timestamp')
                
                grafana_metrics['temperature_variance'].append({
                    'timestamp': timestamp,
                    'occupied_variance': data.get('occupied_variance'),
                    'unoccupied_variance': data.get('unoccupied_variance'),
                    'occupied_mean': data.get('occupied_mean'),
                    'unoccupied_mean': data.get('unoccupied_mean'),
                    'occupied_rooms_count': data.get('occupied_rooms_count'),
                    'unoccupied_rooms_count': data.get('unoccupied_rooms_count')
                })
            
            elif entry_type == 'efficiency_metrics':
                # Process efficiency metrics
                timestamp = data.get('timestamp')
                temp_efficiency = data.get('temperature_efficiency', {})
                occupancy_efficiency = data.get('occupancy_efficiency', {})
                
                grafana_metrics['efficiency_scores'].append({
                    'timestamp': timestamp,
                    'overall_efficiency_score': temp_efficiency.get('overall_efficiency_score'),
                    'occupied_rooms_variance': temp_efficiency.get('occupied_rooms_variance'),
                    'unoccupied_rooms_variance': temp_efficiency.get('unoccupied_rooms_variance'),
                    'occupancy_percentage': occupancy_efficiency.get('occupancy_percentage'),
                    'vent_control_efficiency': occupancy_efficiency.get('vent_control_efficiency')
                })
        
        return grafana_metrics
    
    def export_to_influxdb_format(self, grafana_metrics: Dict[str, Any]) -> List[str]:
        """Export metrics in InfluxDB line protocol format for Grafana"""
        
        lines = []
        
        for metric_type, data_points in grafana_metrics.items():
            if not data_points:
                continue
                
            for point in data_points:
                timestamp = point.get('timestamp', datetime.now().isoformat())
                
                if metric_type == 'temperature_drift':
                    # Convert timestamp to nanoseconds for InfluxDB
                    ts_ns = int(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp() * 1e9)
                    
                    tags = f"room={point['room']},occupancy={point['occupancy']},room_type={point['room_type']}"
                    fields = f"temperature={point['temperature']},drift_from_setpoint={point['drift_from_setpoint']},vent_position={point['vent_position']},ecobee_setpoint={point['ecobee_setpoint']}"
                    
                    lines.append(f"temperature_drift,{tags} {fields} {int(ts_ns)}")
                
                elif metric_type == 'temperature_variance':
                    ts_ns = int(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp() * 1e9)
                    
                    fields = []
                    if point.get('occupied_variance') is not None:
                        fields.append(f"occupied_variance={point['occupied_variance']}")
                    if point.get('unoccupied_variance') is not None:
                        fields.append(f"unoccupied_variance={point['unoccupied_variance']}")
                    if point.get('occupied_mean') is not None:
                        fields.append(f"occupied_mean={point['occupied_mean']}")
                    if point.get('unoccupied_mean') is not None:
                        fields.append(f"unoccupied_mean={point['unoccupied_mean']}")
                    fields.append(f"occupied_rooms_count={point['occupied_rooms_count']}")
                    fields.append(f"unoccupied_rooms_count={point['unoccupied_rooms_count']}")
                    
                    lines.append(f"temperature_variance {','.join(fields)} {int(ts_ns)}")
                
                elif metric_type == 'efficiency_scores':
                    ts_ns = int(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp() * 1e9)
                    
                    fields = []
                    if point.get('overall_efficiency_score') is not None:
                        fields.append(f"overall_efficiency_score={point['overall_efficiency_score']}")
                    if point.get('occupied_rooms_variance') is not None:
                        fields.append(f"occupied_rooms_variance={point['occupied_rooms_variance']}")
                    if point.get('unoccupied_rooms_variance') is not None:
                        fields.append(f"unoccupied_rooms_variance={point['unoccupied_rooms_variance']}")
                    if point.get('occupancy_percentage') is not None:
                        fields.append(f"occupancy_percentage={point['occupancy_percentage']}")
                    if point.get('vent_control_efficiency') is not None:
                        fields.append(f"vent_control_efficiency={point['vent_control_efficiency']}")
                    
                    lines.append(f"efficiency_scores {','.join(fields)} {int(ts_ns)}")
        
        return lines

def main():
    """Main function to parse logs and generate metrics"""
    parser = TemperatureMetricsParser()
    
    # Read log lines from stdin or file
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            log_lines = f.readlines()
    else:
        log_lines = sys.stdin.readlines()
    
    # Parse all log lines
    parsed_data = []
    for line in log_lines:
        parsed = parser.parse_log_line(line.strip())
        if parsed:
            parsed_data.append(parsed)
    
    # Generate Grafana metrics
    grafana_metrics = parser.generate_grafana_metrics(parsed_data)
    
    # Export to InfluxDB format
    influxdb_lines = parser.export_to_influxdb_format(grafana_metrics)
    
    # Output results
    print("=== PARSED METRICS SUMMARY ===")
    print(f"Temperature drift entries: {len(grafana_metrics['temperature_drift'])}")
    print(f"Temperature variance entries: {len(grafana_metrics['temperature_variance'])}")
    print(f"Efficiency score entries: {len(grafana_metrics['efficiency_scores'])}")
    print(f"Total InfluxDB lines: {len(influxdb_lines)}")
    
    print("\n=== INFLUXDB LINE PROTOCOL ===")
    for line in influxdb_lines:
        print(line)
    
    # Save to file for Grafana import
    with open('temperature_metrics_influxdb.txt', 'w') as f:
        for line in influxdb_lines:
            f.write(line + '\n')
    
    print(f"\nMetrics saved to: temperature_metrics_influxdb.txt")
    print(f"Import this file into InfluxDB for Grafana visualization")

if __name__ == "__main__":
    main()
