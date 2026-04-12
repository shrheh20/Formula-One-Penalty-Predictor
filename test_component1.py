"""
Test script for Component 1: Grid Penalty Predictor
Run this to verify everything is working before shipping
"""

import sys
from component_tracker import F1ComponentTracker
import json

def test_component_tracker():
    """Test the core component tracking functionality."""
    print("\n" + "="*60)
    print("Testing Component 1: Grid Penalty Predictor")
    print("="*60 + "\n")
    
    # Initialize tracker
    print("1. Initializing F1ComponentTracker...")
    tracker = F1ComponentTracker()
    print("   ✓ Tracker initialized")
    
    # Load FIA-backed data
    print("\n2. Loading FIA-backed 2026 component snapshot...")
    try:
        tracker.load_component_data(tracker.DEFAULT_DATA_SOURCE)
        print(f"   ✓ Loaded data for {len(tracker.component_data)} drivers")
    except FileNotFoundError:
        print("   ✗ Error: FIA snapshot CSV not found")
        print("   Make sure you're running this from the F1-PenaltyPredictor directory")
        return False
    except Exception as e:
        print(f"   ✗ Error loading data: {e}")
        return False
    
    # Test predictions
    print("\n3. Generating penalty predictions for Race 4...")
    try:
        predictions = tracker.predict_penalties(4)
        print(f"   ✓ Generated predictions for {len(predictions)} at-risk drivers")
        
        if len(predictions) > 0:
            print("\n   Top 3 High-Risk Drivers:")
            for i, pred in enumerate(predictions[:3], 1):
                print(f"   {i}. {pred['driver']}: {pred['penalty_probability']:.0f}% risk")
                print(f"      {pred['recommendation']}")
        else:
            print("   ⚠ Warning: No high-risk drivers found (this might be okay)")
    except Exception as e:
        print(f"   ✗ Error generating predictions: {e}")
        return False
    
    # Test circuit analysis
    print("\n4. Testing strategic circuit analysis...")
    try:
        circuits = tracker.get_strategic_circuits()
        print(f"   ✓ Loaded {len(circuits['best_for_penalties'])} best circuits")
        print(f"   ✓ Loaded {len(circuits['worst_for_penalties'])} worst circuits")
        
        print("\n   Best circuit for penalties:")
        best = circuits['best_for_penalties'][0]
        print(f"   • {best['circuit']}: {best['reason']}")
    except Exception as e:
        print(f"   ✗ Error getting circuits: {e}")
        return False
    
    # Test full report generation
    print("\n5. Testing full report generation...")
    try:
        report = tracker.generate_report("Bahrain GP", 4)
        print(f"   ✓ Generated report for {report['race']}")
        print(f"   ✓ High risk drivers: {len(report['high_risk_drivers'])}")
        print(f"   ✓ Moderate risk drivers: {len(report['moderate_risk_drivers'])}")
        print(f"   ✓ Betting insights: {len(report['betting_insights'])}")
    except Exception as e:
        print(f"   ✗ Error generating report: {e}")
        return False
    
    # Test betting insights
    print("\n6. Testing betting insights...")
    try:
        betting_insights = tracker._generate_betting_insights(predictions, "Bahrain")
        if len(betting_insights) > 0:
            print(f"   ✓ Generated {len(betting_insights)} betting insights")
            print("\n   Sample insight:")
            insight = betting_insights[0]
            print(f"   • Driver: {insight['driver']}")
            print(f"   • Market: {insight['market']}")
            print(f"   • Insight: {insight['insight']}")
            print(f"   • Confidence: {insight['confidence']}")
        else:
            print("   ⚠ No betting insights (might be okay if no high-risk drivers)")
    except Exception as e:
        print(f"   ✗ Error generating betting insights: {e}")
        return False
    
    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED - Component 1 is ready to ship!")
    print("="*60 + "\n")
    
    print("Next steps:")
    print("1. Start the API: python api.py")
    print("2. Open dashboard.html in your browser")
    print("3. Test the endpoints listed in DEPLOYMENT.md")
    print("4. Refresh the FIA snapshot when new race documents are published")
    print("5. Ship it! 🚀\n")
    
    return True

def test_api_imports():
    """Test that API dependencies are available."""
    print("\nTesting API dependencies...")
    
    try:
        import flask
        print("   ✓ Flask installed")
    except ImportError:
        print("   ✗ Flask not installed - run: python -m pip install -r requirements.txt")
        return False
    
    try:
        import flask_cors
        print("   ✓ Flask-CORS installed")
    except ImportError:
        print("   ✗ Flask-CORS not installed - run: python -m pip install -r requirements.txt")
        return False
    
    try:
        import pandas
        print("   ✓ Pandas installed")
    except ImportError:
        print("   ✗ Pandas not installed - run: python -m pip install -r requirements.txt")
        return False
    
    return True

if __name__ == "__main__":
    print("\n🏎️  F1 Intelligence System - Component 1 Test Suite\n")
    
    # Test dependencies first
    if not test_api_imports():
        print("\n⚠ Please install missing dependencies:")
        print("python -m pip install -r requirements.txt\n")
        sys.exit(1)
    
    # Run main tests
    success = test_component_tracker()
    
    if success:
        sys.exit(0)
    else:
        print("\n✗ Tests failed - please check errors above\n")
        sys.exit(1)
