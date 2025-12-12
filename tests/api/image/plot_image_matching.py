#!/usr/bin/env python3
"""
Parse pytest output and generate image matching test results chart.

Usage:
    # Run tests and save log
    pytest -v -s tests/api/image/test_image_matching.py 2>&1 | tee tests/api/image/test_image_matching.log
    
    # Generate chart
    python tests/api/image/plot_image_matching.py
"""

import sys
import re
import os
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
    
    import ast
    # Find class body and extract default values
    for line in content.split('\n'):
        line = line.strip()
        for key in ['image_threshold', 'image_offset']:
            if line.startswith(f'{key}:'):
                # Extract value after '='
                if '=' in line:
                    val_str = line.split('=')[1].strip()
                    try:
                        config[key] = float(val_str)
                    except ValueError:
                        pass
    return config

_config = _parse_config(_config_path)
IMAGE_THRESHOLD = (_config.get('image_threshold', 0.90) - _config.get('image_offset', 0.0125)) * 100
IMAGE_THRESHOLD_RAW = _config.get('image_threshold', 0.90) * 100
IMAGE_OFFSET_RAW = _config.get('image_offset', 0.0125) * 100

def parse_pytest_output(lines):
    """Parse pytest output for image matching results."""
    
    results = {
        'right': [],
        'left': [],
        'top': [],
        'bottom': [],
        'noise': [],
        'brightness': [],
        'contrast': [],
        'resize': [],
        'jpeg': [],
        'blur': [],
        'special': []
    }
    
    # Pattern: "Cutoff RIGHT 6%: image=94.5%, status=near_match"
    cutoff_pattern = re.compile(
        r'Cutoff (RIGHT|LEFT|TOP|BOTTOM) (\d+)%: image=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Noise 6%: image=100.0%, status=exact_match"
    modification_pattern = re.compile(
        r'(Noise|Brightness|Contrast|Resize|JPEG|Blur) (\d+)%: image=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Exact match: image=100.0%, status=exact_match"
    exact_pattern = re.compile(
        r'Exact match: image=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Different image: image=53.9%, status=no_match"
    different_pattern = re.compile(
        r'Different image: image=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Grayscale: image=100.0%, status=exact_match"
    grayscale_pattern = re.compile(
        r'Grayscale: image=([\d.]+)%, status=(\w+)'
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
                # Default to True if no PASSED/FAILED found on this line
                continue
            pending_result = None
            continue
        
        # Check cutoff tests
        match = cutoff_pattern.search(line)
        if match:
            cutoff_type = match.group(1).lower()
            pct = int(match.group(2))
            image = float(match.group(3))
            status = match.group(4)
            
            result = {
                'pct': pct,
                'image': image,
                'status': status,
                'pytest_passed': True
            }
            results[cutoff_type].append(result)
            pending_result = result
            continue
        
        # Check modification tests
        match = modification_pattern.search(line)
        if match:
            mod_type = match.group(1).lower()
            pct = int(match.group(2))
            image = float(match.group(3))
            status = match.group(4)
            
            result = {
                'pct': pct,
                'image': image,
                'status': status,
                'pytest_passed': True
            }
            results[mod_type].append(result)
            pending_result = result
            continue
        
        # Check exact match
        match = exact_pattern.search(line)
        if match:
            result = {
                'name': 'Exact Match',
                'image': float(match.group(1)),
                'status': match.group(2),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
            continue
        
        # Check different image
        match = different_pattern.search(line)
        if match:
            result = {
                'name': 'Different Image',
                'image': float(match.group(1)),
                'status': match.group(2),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
            continue
        
        # Check grayscale
        match = grayscale_pattern.search(line)
        if match:
            result = {
                'name': 'Grayscale',
                'image': float(match.group(1)),
                'status': match.group(2),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
    
    # Sort by percentage
    for key in results:
        if key != 'special' and results[key]:
            results[key].sort(key=lambda x: x['pct'])
    
    return results


def generate_chart(results, output_path='image_test_results.png'):
    """Generate matplotlib chart from parsed results."""
    
    image_threshold = IMAGE_THRESHOLD
    
    # Group 1: Cutoffs (spatial modifications)
    cutoff_types = ['right', 'left', 'top', 'bottom']
    # Group 2: Quality modifications
    quality_types = ['noise', 'brightness', 'contrast', 'blur']
    # Group 3: Format/size modifications  
    format_types = ['resize', 'jpeg']
    
    # Format offset display (handle negative offsets)
    image_offset_sign = '-' if IMAGE_OFFSET_RAW >= 0 else '+'
    image_offset_display = abs(IMAGE_OFFSET_RAW)
    
    fig, axes = plt.subplots(3, 4, figsize=(16, 12))
    fig.suptitle(f'Image Matching Test Results\n'
                 f'Image Threshold: {image_threshold:.2f}% ({IMAGE_THRESHOLD_RAW:.0f}% {image_offset_sign} {image_offset_display:.2f}% offset)', 
                 fontsize=14, fontweight='bold')
    
    # Row 1: Cutoffs
    cutoff_data = [
        ('Cutoff RIGHT', results['right'], (80, 100)),
        ('Cutoff LEFT', results['left'], (80, 100)),
        ('Cutoff TOP', results['top'], (80, 100)),
        ('Cutoff BOTTOM', results['bottom'], (80, 100)),
    ]
    
    for ax, (title, data, ylim) in zip(axes[0], cutoff_data):
        plot_subplot(ax, title, data, ylim, image_threshold)
    
    # Row 2: Quality modifications
    quality_data = [
        ('Noise', results['noise'], (90, 102)),
        ('Brightness', results['brightness'], (90, 102)),
        ('Contrast', results['contrast'], (90, 102)),
        ('Blur', results['blur'], (85, 100)),
    ]
    
    for ax, (title, data, ylim) in zip(axes[1], quality_data):
        plot_subplot(ax, title, data, ylim, image_threshold)
    
    # Row 3: Format modifications + Special cases
    format_data = [
        ('Resize', results['resize'], (90, 102)),
        ('JPEG Compression', results['jpeg'], (90, 102)),
    ]
    
    for ax, (title, data, ylim) in zip(axes[2][:2], format_data):
        plot_subplot(ax, title, data, ylim, image_threshold)
    
    # Special cases bar chart
    ax_special = axes[2][2]
    if results['special']:
        names = [s['name'] for s in results['special']]
        values = [s['image'] for s in results['special']]
        pytest_results = [s.get('pytest_passed', True) for s in results['special']]
        colors = ['#22c55e' if p else '#ef4444' for p in pytest_results]
        
        bars = ax_special.bar(names, values, color=colors, edgecolor='black', linewidth=1)
        offset_sign = '-' if IMAGE_OFFSET_RAW >= 0 else '+'
        ax_special.axhline(y=image_threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
                          label=f'Threshold: {image_threshold:.1f}% ({IMAGE_THRESHOLD_RAW:.0f}% {offset_sign} {abs(IMAGE_OFFSET_RAW):.2f}%)')
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
    
    # Hide last cell
    axes[2][3].axis('off')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.93)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Chart saved to {output_path}")


def plot_subplot(ax, title, data, ylim, threshold):
    """Plot a single subplot."""
    if not data:
        ax.set_title(f'{title} (no data)')
        ax.set_ylim(ylim)
        return
    
    pcts = [d['pct'] for d in data]
    image_vals = [d['image'] for d in data]
    pytest_results = [d.get('pytest_passed', True) for d in data]
    
    # Calculate pass/fail
    pass_count = sum(1 for p in pytest_results if p)
    
    # Plot line
    ax.plot(pcts, image_vals, 'b-', linewidth=2, label='Image Match %')
    
    # Color markers by pytest result and add tick/cross
    for pct, image, passed in zip(pcts, image_vals, pytest_results):
        color = '#22c55e' if passed else '#ef4444'
        ax.plot(pct, image, 'o', markersize=10, color=color, zorder=5)
        
        # Add tick or cross
        indicator = '✓' if passed else '✗'
        ax.annotate(indicator, (pct, image), textcoords="offset points", 
                    xytext=(0, 8), ha='center', fontsize=8, fontweight='bold', color=color)
    
    # Threshold line with details in label
    offset_sign = '-' if IMAGE_OFFSET_RAW >= 0 else '+'
    ax.axhline(y=threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
               label=f'Threshold: {threshold:.1f}% ({IMAGE_THRESHOLD_RAW:.0f}% {offset_sign} {abs(IMAGE_OFFSET_RAW):.2f}%)')
    
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


def main():
    default_log = 'tests/api/image/test_image_matching.log'
    default_output = 'tests/api/image/image_test_results.png'
    
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
        print(f"Run: pytest -v -s tests/api/image/test_image_matching.py 2>&1 | tee {default_log}")
        sys.exit(1)
    
    results = parse_pytest_output(lines)
    generate_chart(results, output_path)


if __name__ == '__main__':
    main()