#!/usr/bin/env python3
"""
Parse pytest output and generate video matching test results chart.

Usage:
    # Run tests and save log
    pytest -v -s tests/api/video/test_video_matching.py 2>&1 | tee tests/api/video/test_video_matching.log
    
    # Generate chart
    python tests/api/video/plot_video_matching.py
"""

import sys
import re
import os
import numpy as np
import matplotlib.pyplot as plt

# Import config for thresholds
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, '..', '..', '..'))
_config_path = os.path.join(_project_root, 'matching', 'app', 'config.py')

if not os.path.exists(_config_path):
    raise ImportError(f"config.py not found at {_config_path}")

# Parse config.py directly to avoid pydantic dependency
def _parse_config(config_path):
    """Extract threshold values from config.py without importing it."""
    config = {}
    with open(config_path, 'r') as f:
        content = f.read()
    
    for line in content.split('\n'):
        line = line.strip()
        for key in ['video_threshold', 'video_offset']:
            if line.startswith(f'{key}:'):
                if '=' in line:
                    val_str = line.split('=')[1].strip()
                    try:
                        config[key] = float(val_str)
                    except ValueError:
                        pass
    return config

_config = _parse_config(_config_path)
VIDEO_THRESHOLD = (_config.get('video_threshold', 0.85) - _config.get('video_offset', 0.03)) * 100
VIDEO_THRESHOLD_RAW = _config.get('video_threshold', 0.85) * 100
VIDEO_OFFSET_RAW = _config.get('video_offset', 0.03) * 100


def parse_pytest_output(lines):
    """Parse pytest output for video matching results."""
    
    results = {
        'crop_right': [],
        'crop_left': [],
        'crop_top': [],
        'crop_bottom': [],
        'trim_start': [],
        'trim_end': [],
        'trim_middle': [],
        'speed_decrease': [],
        'speed_increase': [],
        'special': []
    }
    
    # Pattern: "Crop RIGHT 10%: video=83.5%, status=near_match"
    crop_pattern = re.compile(
        r'Crop (RIGHT|LEFT|TOP|BOTTOM) (\d+)%: video=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Trim START 10%: video=98.5%, status=near_match"
    trim_pattern = re.compile(
        r'Trim (START|END|MIDDLE) (\d+)%: video=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Speed -10%: video=93.4%, status=near_match" or "Speed +10%: video=86.2%, status=near_match"
    speed_pattern = re.compile(
        r'Speed ([+-])(\d+)%: video=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Exact match: video=100.0%, status=exact_match"
    exact_pattern = re.compile(
        r'Exact match: video=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Different video: video=0.0%, status=no_match"
    different_pattern = re.compile(
        r'Different video: video=([\d.]+)%, status=(\w+)'
    )
    
    pending_result = None
    
    for line in lines:
        # Check if this line indicates test passed/failed
        if pending_result is not None:
            if 'PASSED' in line:
                pending_result['pytest_passed'] = True
            elif 'FAILED' in line:
                pending_result['pytest_passed'] = False
            else:
                continue
            pending_result = None
            continue
        
        # Check crop tests
        match = crop_pattern.search(line)
        if match:
            crop_type = f"crop_{match.group(1).lower()}"
            pct = int(match.group(2))
            video = float(match.group(3))
            status = match.group(4)
            
            result = {
                'pct': pct,
                'video': video,
                'status': status,
                'pytest_passed': True
            }
            results[crop_type].append(result)
            pending_result = result
            continue
        
        # Check trim tests
        match = trim_pattern.search(line)
        if match:
            trim_type = f"trim_{match.group(1).lower()}"
            pct = int(match.group(2))
            video = float(match.group(3))
            status = match.group(4)
            
            result = {
                'pct': pct,
                'video': video,
                'status': status,
                'pytest_passed': True
            }
            results[trim_type].append(result)
            pending_result = result
            continue
        
        # Check speed tests
        match = speed_pattern.search(line)
        if match:
            sign = match.group(1)
            pct = int(match.group(2))
            video = float(match.group(3))
            status = match.group(4)
            
            speed_type = 'speed_decrease' if sign == '-' else 'speed_increase'
            
            result = {
                'pct': pct,
                'video': video,
                'status': status,
                'pytest_passed': True
            }
            results[speed_type].append(result)
            pending_result = result
            continue
        
        # Check exact match
        match = exact_pattern.search(line)
        if match:
            result = {
                'name': 'Exact Match',
                'video': float(match.group(1)),
                'status': match.group(2),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
            continue
        
        # Check different video
        match = different_pattern.search(line)
        if match:
            result = {
                'name': 'Different Video',
                'video': float(match.group(1)),
                'status': match.group(2),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
            continue
    
    # Sort by percentage
    for key in results:
        if key != 'special' and results[key]:
            results[key].sort(key=lambda x: x['pct'])
    
    return results


def generate_chart(results, output_path='video_test_results.png'):
    """Generate matplotlib chart from parsed results."""
    
    video_threshold = VIDEO_THRESHOLD
    
    # Format offset display (handle negative offsets)
    video_offset_sign = '-' if VIDEO_OFFSET_RAW >= 0 else '+'
    video_offset_display = abs(VIDEO_OFFSET_RAW)
    
    fig, axes = plt.subplots(3, 4, figsize=(18, 16))
    fig.suptitle(f'Video Matching Test Results\n'
                 f'Video Threshold: {video_threshold:.1f}% ({VIDEO_THRESHOLD_RAW:.0f}% {video_offset_sign} {video_offset_display:.0f}% offset)', 
                 fontsize=14, fontweight='bold')
    
    # Row 1: Crop tests (ylim=None for dynamic y-axis based on data)
    crop_data = [
        ('Crop RIGHT', results['crop_right'], None),
        ('Crop LEFT', results['crop_left'], None),
        ('Crop TOP', results['crop_top'], None),
        ('Crop BOTTOM', results['crop_bottom'], None),
    ]
    
    for ax, (title, data, ylim) in zip(axes[0], crop_data):
        plot_subplot(ax, title, data, ylim, video_threshold)
    
    # Row 2: Trim tests + Special cases (ylim=None for dynamic y-axis)
    trim_data = [
        ('Trim START', results['trim_start'], None),
        ('Trim END', results['trim_end'], None),
        ('Trim MIDDLE', results['trim_middle'], None),
    ]
    
    for ax, (title, data, ylim) in zip(axes[1][:3], trim_data):
        plot_subplot(ax, title, data, ylim, video_threshold)
    
    # Special cases bar chart
    ax_special = axes[1][3]
    if results['special']:
        names = [s['name'] for s in results['special']]
        values = [s['video'] for s in results['special']]
        pytest_results = [s.get('pytest_passed', True) for s in results['special']]
        colors = ['#22c55e' if p else '#ef4444' for p in pytest_results]
        
        bars = ax_special.bar(names, values, color=colors, edgecolor='black', linewidth=1)
        offset_sign = '-' if VIDEO_OFFSET_RAW >= 0 else '+'
        ax_special.axhline(y=video_threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
                          label=f'Threshold: {video_threshold:.1f}% ({VIDEO_THRESHOLD_RAW:.0f}% {offset_sign} {abs(VIDEO_OFFSET_RAW):.0f}%)')
        ax_special.set_ylim(0, 105)
        ax_special.set_ylabel('Match %', fontsize=8)
        ax_special.set_title('Special Cases', fontsize=10, fontweight='bold')
        ax_special.tick_params(axis='x', labelsize=8, rotation=15)
        ax_special.tick_params(axis='y', labelsize=8)
        ax_special.grid(True, alpha=0.3, axis='y')
        ax_special.legend(loc='lower right', fontsize=6)
        
        # Add value labels on bars
        for bar, val in zip(bars, values):
            ax_special.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                           f'{val:.1f}%', ha='center', va='bottom', fontsize=8)
    else:
        ax_special.axis('off')
    
    # Row 3: Speed tests (ylim=None for dynamic y-axis)
    speed_data = [
        ('Speed Decrease (-)', results['speed_decrease'], None),
        ('Speed Increase (+)', results['speed_increase'], None),
    ]
    
    for ax, (title, data, ylim) in zip(axes[2][:2], speed_data):
        plot_subplot(ax, title, data, ylim, video_threshold)
    
    # Hide unused cells in row 3
    axes[2][2].axis('off')
    axes[2][3].axis('off')
    
    # Create combined chart as a separate axes spanning the bottom
    # Doubled height from 0.12 to 0.24
    ax_combined = fig.add_axes([0.08, 0.03, 0.88, 0.22])  # [left, bottom, width, height]
    plot_combined_overlay(ax_combined, results, video_threshold)
    
    plt.subplots_adjust(top=0.93, bottom=0.32, hspace=0.40, wspace=0.25)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Chart saved to {output_path}")


def plot_subplot(ax, title, data, ylim, threshold):
    """Plot a single subplot."""
    if not data:
        ax.set_title(f'{title} (no data)')
        if ylim:
            ax.set_ylim(ylim)
        return
    
    pcts = [d['pct'] for d in data]
    video_vals = [d['video'] for d in data]
    pytest_results = [d.get('pytest_passed', True) for d in data]
    
    # Calculate pass/fail
    pass_count = sum(1 for p in pytest_results if p)
    
    # Auto-calculate ylim based on data if None provided
    if ylim is None:
        min_val = min(video_vals)
        max_val = max(video_vals)
        val_range = max_val - min_val
        
        # Special case: all values are 0 (no matches)
        if max_val == 0:
            ylim = (-5, 20)
        # Special case: all values are the same or very close
        elif val_range < 5:
            # Add padding to show detail
            padding = max(5, (15 - val_range) / 2)
            ylim = (max(-2, min_val - padding), min(105, max_val + padding))
        else:
            # Normal case: add small padding
            padding = max(2, val_range * 0.1)
            ylim = (max(-2, min_val - padding), min(105, max_val + padding))
        
        # Ensure threshold is visible if it's close to the data range
        if threshold >= ylim[0] - 10 and threshold <= ylim[1] + 10:
            ylim = (min(ylim[0], threshold - 3), max(ylim[1], threshold + 3))
    
    # Plot line first
    ax.plot(pcts, video_vals, 'b-', linewidth=2, label='Video Match %', zorder=3)
    
    # Color markers by pytest result and add tick/cross - draw on top
    for pct, video, passed in zip(pcts, video_vals, pytest_results):
        color = '#22c55e' if passed else '#ef4444'
        ax.plot(pct, video, 'o', markersize=10, color=color, zorder=5, 
                markeredgecolor='black', markeredgewidth=0.5)
        
        # Add tick or cross
        indicator = '✓' if passed else '✗'
        ax.annotate(indicator, (pct, video), textcoords="offset points", 
                    xytext=(0, 8), ha='center', fontsize=8, fontweight='bold', color=color)
    
    # Threshold line with details in label
    offset_sign = '-' if VIDEO_OFFSET_RAW >= 0 else '+'
    ax.axhline(y=threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
               label=f'Threshold: {threshold:.1f}% ({VIDEO_THRESHOLD_RAW:.0f}% {offset_sign} {abs(VIDEO_OFFSET_RAW):.0f}%)')
    
    # Shade pass/fail regions based on status (near_match/exact_match vs no_match)
    if pcts:
        min_pct = min(pcts) - 1
        max_pct = max(pcts) + 1
        
        match_pcts = [d['pct'] for d in data if d['status'] in ['near_match', 'exact_match']]
        no_match_pcts = [d['pct'] for d in data if d['status'] == 'no_match']
        
        if match_pcts and no_match_pcts:
            # Boundary between last match and first no_match
            last_match = max(match_pcts)
            first_no_match = min(no_match_pcts)
            boundary = (last_match + first_no_match) / 2
            ax.axvspan(min_pct, boundary, alpha=0.1, color='green')
            ax.axvspan(boundary, max_pct, alpha=0.1, color='red')
        elif match_pcts:
            ax.axvspan(min_pct, max_pct, alpha=0.1, color='green')
        elif no_match_pcts:
            ax.axvspan(min_pct, max_pct, alpha=0.1, color='red')
    
    ax.set_title(f'{title} ({pass_count}/{len(data)})', fontsize=10, fontweight='bold')
    ax.set_ylim(ylim[0], ylim[1])
    ax.set_xlim(min(pcts) - 1, max(pcts) + 1)
    ax.set_xticks(pcts)
    ax.set_xlabel('Modification %', fontsize=8)
    ax.set_ylabel('Match %', fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis='both', labelsize=8)
    ax.legend(loc='lower left', fontsize=6)


def plot_combined_overlay(ax, results, threshold):
    """Plot all test types overlaid on a single chart with inverted log Y-axis."""
    
    # Define colors and markers for each test type
    # Speed decrease uses bright orange to stand out at top of chart
    styles = {
        'crop_right': {'color': '#e74c3c', 'marker': 'o', 'label': 'Crop RIGHT'},
        'crop_left': {'color': '#c0392b', 'marker': 's', 'label': 'Crop LEFT'},
        'crop_top': {'color': '#3498db', 'marker': '^', 'label': 'Crop TOP'},
        'crop_bottom': {'color': '#2980b9', 'marker': 'v', 'label': 'Crop BOTTOM'},
        'trim_start': {'color': '#2ecc71', 'marker': 'D', 'label': 'Trim START'},
        'trim_end': {'color': '#27ae60', 'marker': 'p', 'label': 'Trim END'},
        'trim_middle': {'color': '#1abc9c', 'marker': 'h', 'label': 'Trim MIDDLE'},
        'speed_decrease': {'color': '#ff6600', 'marker': '<', 'label': 'Speed -'},
        'speed_increase': {'color': '#8e44ad', 'marker': '>', 'label': 'Speed +'},
    }
    
    all_pcts = []
    
    for key, style in styles.items():
        data = results.get(key, [])
        if not data:
            continue
        
        pcts = [d['pct'] for d in data]
        video_vals = [d['video'] for d in data]
        all_pcts.extend(pcts)
        
        # Use larger markers for speed tests to make them more visible
        marker_size = 8 if 'speed' in key else 6
        
        ax.plot(pcts, video_vals, 
                color=style['color'], 
                marker=style['marker'],
                linewidth=1.5,
                markersize=marker_size,
                label=style['label'],
                alpha=0.8)
    
    # Threshold line
    offset_sign = '-' if VIDEO_OFFSET_RAW >= 0 else '+'
    ax.axhline(y=threshold, color='black', linestyle='--', linewidth=2, alpha=0.7,
               label=f'Threshold: {threshold:.0f}%')
    
    if all_pcts:
        ax.set_xlim(min(all_pcts) - 2, max(all_pcts) + 2)
    
    # Inverted logarithmic scale on Y-axis
    # This spreads out values near 100% and compresses values near 0%
    def forward(y):
        y = np.asarray(y, dtype=float)
        return -np.log10(100.5 - np.clip(y, 0, 100))
    
    def inverse(y):
        y = np.asarray(y, dtype=float)
        return 100.5 - np.power(10, -y)
    
    ax.set_yscale('function', functions=(forward, inverse))
    ax.set_ylim(0, 100)
    
    # Set custom tick locations for better readability
    ax.set_yticks([0, 10, 20, 30, 40, 50, 60, 70, 80, 85, 90, 95, 98, 99, 100])
    ax.set_yticklabels(['0', '10', '20', '30', '40', '50', '60', '70', '80', '85', '90', '95', '98', '99', '100'])
    
    ax.set_xlabel('Modification %', fontsize=10)
    ax.set_ylabel('Video Match % (inverted log scale)', fontsize=10)
    ax.set_title('All Tests Combined', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower left', fontsize=8, ncol=5)


def main():
    default_log = 'tests/api/video/test_video_matching.log'
    default_output = 'tests/api/video/video_test_results.png'
    
    # Read from file argument or default
    log_path = sys.argv[1] if len(sys.argv) > 1 else default_log
    output_path = sys.argv[2] if len(sys.argv) > 2 else default_output
    
    # Create output directory if needed
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Log file not found: {log_path}")
        print(f"Run: pytest -v -s tests/api/video/test_video_matching.py 2>&1 | tee {default_log}")
        sys.exit(1)
    
    results = parse_pytest_output(lines)
    generate_chart(results, output_path)


if __name__ == '__main__':
    main()