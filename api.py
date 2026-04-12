"""
F1 Component Tracker API
Simple Flask API to serve penalty predictions
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
from component_tracker import F1ComponentTracker
import json
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Initialize tracker
tracker = F1ComponentTracker()

# Load data on startup
try:
    tracker.load_component_data(tracker.DEFAULT_DATA_SOURCE)
    print("✓ Component data loaded successfully")
except Exception as e:
    print(f"✗ Error loading data: {e}")

@app.route('/')
def home():
    """API documentation endpoint."""
    return jsonify({
        'name': 'F1 Component Tracker API',
        'version': '1.2.0',
        'endpoints': {
            '/api/predictions': 'Get penalty predictions for upcoming race',
            '/api/drivers': 'Get all driver component status',
            '/api/component-allocations': 'Get current allowed 2026 component allocations',
            '/api/driver/<code>': 'Get specific driver details',
            '/api/circuits': 'Get strategic circuit analysis',
            '/api/report/<race_number>': 'Get full race report',
            '/api/betting-insights': 'Get betting-focused penalty insights',
            '/api/health': 'Get API health and data status',
            '/api/sources': 'Get the FIA document manifest behind the current dataset'
        }
    })

@app.route('/api/predictions')
def get_predictions():
    """Get penalty predictions for the next race."""
    race_number = request.args.get('race', type=int, default=4)
    
    try:
        predictions = tracker.predict_penalties(race_number)
        return jsonify({
            'success': True,
            'race_number': race_number,
            'predictions': predictions
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/drivers')
def get_all_drivers():
    """Get component status for all drivers."""
    try:
        drivers_data = []
        for driver, components in tracker.component_data.items():
            driver_summary = {
                'driver': driver,
                'full_name': tracker.driver_info.get(driver, {}).get('full_name'),
                'team': tracker.driver_info.get(driver, {}).get('team'),
                'team_color': tracker.driver_info.get(driver, {}).get('team_color'),
                'team_badge_url': tracker.driver_info.get(driver, {}).get('team_badge_url'),
                'sidecar_url': tracker.driver_info.get(driver, {}).get('sidecar_url'),
                'photo_url': tracker.driver_info.get(driver, {}).get('photo_url'),
                'car_number': tracker.driver_info.get(driver, {}).get('car_number'),
                'components': {}
            }
            
            for comp_type, data in components.items():
                if data['limit'] is not None:
                    driver_summary['components'][comp_type] = {
                        'count': data['count'],
                        'limit': data['limit'],
                        'status': 'critical' if data['count'] >= data['limit'] else 
                                 'warning' if data['count'] == data['limit'] - 1 else 'ok'
                    }
            
            drivers_data.append(driver_summary)
        
        return jsonify({
            'success': True,
            'drivers': drivers_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/component-allocations')
def get_component_allocations():
    """Get the current tracked component allocations."""
    try:
        return jsonify({
            'success': True,
            'component_allocations': tracker.get_component_allocations()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/driver/<driver_code>')
def get_driver_detail(driver_code):
    """Get detailed component history for a specific driver."""
    driver_code = driver_code.upper()
    
    if driver_code not in tracker.component_data:
        return jsonify({
            'success': False,
            'error': f'Driver {driver_code} not found'
        }), 404
    
    try:
        driver_data = tracker.component_data[driver_code]
        return jsonify({
            'success': True,
            'driver': driver_code,
            'metadata': tracker.driver_info.get(driver_code, {}),
            'components': driver_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/circuits')
def get_circuits():
    """Get strategic circuit analysis."""
    try:
        circuits = tracker.get_strategic_circuits()
        return jsonify({
            'success': True,
            'circuits': circuits
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/report/<int:race_number>')
def get_race_report(race_number):
    """Get comprehensive report for a specific race."""
    race_name = request.args.get('name', f'Race {race_number}')
    
    try:
        report = tracker.generate_report(race_name, race_number)
        return jsonify({
            'success': True,
            'report': report
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/betting-insights')
def get_betting_insights():
    """Get betting-specific insights."""
    race_number = request.args.get('race', type=int, default=4)
    
    try:
        predictions = tracker.predict_penalties(race_number)
        insights = tracker._generate_betting_insights(predictions, f"Race {race_number}")
        
        return jsonify({
            'success': True,
            'race_number': race_number,
            'insights': insights,
            'summary': {
                'high_risk_count': len([p for p in predictions if p['penalty_probability'] >= 70]),
                'moderate_risk_count': len([p for p in predictions if 30 <= p['penalty_probability'] < 70]),
                'total_at_risk': len(predictions)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'drivers_loaded': len(tracker.component_data),
        'data_source': tracker.data_source,
        'source_manifest': tracker.source_manifest_path
    })

@app.route('/api/sources')
def get_sources():
    """Return the FIA source manifest used to build the current dataset."""
    try:
        return jsonify({
            'success': True,
            'sources': tracker.get_source_manifest()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}

    print("\n" + "="*50)
    print("F1 Component Tracker API Starting...")
    print("="*50)
    print("\nEndpoints available:")
    print(f"  http://localhost:{port}/")
    print(f"  http://localhost:{port}/api/predictions")
    print(f"  http://localhost:{port}/api/drivers")
    print(f"  http://localhost:{port}/api/circuits")
    print(f"  http://localhost:{port}/api/betting-insights")
    print("\nStarting server...\n")
    
    app.run(debug=debug, host='0.0.0.0', port=port)
