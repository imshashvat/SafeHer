"""
SafeHer — ML Training Pipeline
Trains 5 algorithms, compares them, and saves the best model.
"""

import os
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    from lightgbm import LGBMClassifier
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    from imblearn.over_sampling import SMOTE
    HAS_SMOTE = True
except ImportError:
    HAS_SMOTE = False


FEATURE_COLS = [
    'rape', 'kidnapping', 'dowry_deaths', 'assault',
    'insult_to_modesty', 'cruelty_by_husband', 'importation_of_girls',
    'year', 'state_encoded', 'district_encoded',
    'rape_ratio', 'kidnap_ratio', 'assault_ratio', 'cruelty_ratio', 'year_trend'
]

TARGET_COL = 'risk_level'


def get_models():
    """Return dictionary of models to train."""
    models = {
        'RandomForest': RandomForestClassifier(
            n_estimators=200, max_depth=12, random_state=42, n_jobs=-1
        ),
        'LogisticRegression': LogisticRegression(
            max_iter=1000, random_state=42
        ),
        'KNN': KNeighborsClassifier(n_neighbors=7, n_jobs=-1),
    }

    if HAS_XGBOOST:
        models['XGBoost'] = XGBClassifier(
            n_estimators=200, learning_rate=0.1, max_depth=8,
            random_state=42, use_label_encoder=False,
            eval_metric='mlogloss', verbosity=0
        )

    if HAS_LIGHTGBM:
        models['LightGBM'] = LGBMClassifier(
            n_estimators=200, num_leaves=31, learning_rate=0.1,
            random_state=42, verbose=-1
        )

    return models


def train_all_models():
    """Main training pipeline."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    processed_dir = os.path.join(base_dir, 'data', 'processed')
    models_dir = os.path.join(base_dir, 'ml', 'models')
    os.makedirs(models_dir, exist_ok=True)

    # Load processed data
    data_path = os.path.join(processed_dir, 'training_data.csv')
    if not os.path.exists(data_path):
        print("Training data not found. Run preprocess.py first.")
        from ml.preprocess import run_preprocessing
        run_preprocessing()

    df = pd.read_csv(data_path)
    print(f"Loaded training data: {df.shape}")

    # Prepare features and target
    available_features = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available_features].values
    y = df[TARGET_COL].values

    print(f"Features: {available_features}")
    print(f"Target distribution: {np.bincount(y.astype(int))}")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Apply SMOTE for class balancing
    if HAS_SMOTE:
        print("\nApplying SMOTE for class balancing...")
        sm = SMOTE(random_state=42)
        X_train, y_train = sm.fit_resample(X_train, y_train)
        print(f"After SMOTE: {np.bincount(y_train.astype(int))}")

    # Train and evaluate all models
    models = get_models()
    results = {}

    print("\n" + "=" * 60)
    print("TRAINING ALL MODELS")
    print("=" * 60)

    for name, model in models.items():
        print(f"\n--- {name} ---")

        # Cross-validation
        cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring='accuracy')
        print(f"CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")

        # Fit on full training set
        model.fit(X_train, y_train)

        # Evaluate on test set
        y_pred = model.predict(X_test)
        test_acc = accuracy_score(y_test, y_pred)
        print(f"Test Accuracy: {test_acc:.4f}")

        report = classification_report(y_test, y_pred, target_names=['SAFE', 'MODERATE', 'HIGH RISK'], output_dict=True)
        print(classification_report(y_test, y_pred, target_names=['SAFE', 'MODERATE', 'HIGH RISK']))

        results[name] = {
            'cv_mean': float(cv_scores.mean()),
            'cv_std': float(cv_scores.std()),
            'test_accuracy': float(test_acc),
            'report': report
        }

        # Feature importance (for tree-based models)
        if hasattr(model, 'feature_importances_'):
            importance = dict(zip(available_features, model.feature_importances_.tolist()))
            results[name]['feature_importance'] = importance
            top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"Top features: {top_features}")

    # Select best model
    best_name = max(results, key=lambda k: results[k]['test_accuracy'])
    best_model = models[best_name]
    best_acc = results[best_name]['test_accuracy']

    print("\n" + "=" * 60)
    print(f"BEST MODEL: {best_name} (Accuracy: {best_acc:.4f})")
    print("=" * 60)

    # Save best model
    model_path = os.path.join(models_dir, 'crime_model.pkl')
    joblib.dump(best_model, model_path)
    print(f"Saved best model to {model_path}")

    # Save feature list
    joblib.dump(available_features, os.path.join(models_dir, 'feature_cols.pkl'))

    # Save results summary
    results_path = os.path.join(models_dir, 'training_results.json')
    summary = {
        'best_model': best_name,
        'best_accuracy': best_acc,
        'models': {k: {kk: vv for kk, vv in v.items() if kk != 'report'}
                   for k, v in results.items()}
    }
    with open(results_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nAll results saved to {results_path}")
    print("\n--- MODEL COMPARISON ---")
    for name, res in sorted(results.items(), key=lambda x: x[1]['test_accuracy'], reverse=True):
        marker = " ★ BEST" if name == best_name else ""
        print(f"  {name}: {res['test_accuracy']:.4f}{marker}")

    return best_model, results


if __name__ == '__main__':
    train_all_models()
