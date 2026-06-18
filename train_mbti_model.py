"""
MBTI 模型训练脚本。

使用 Random Forest / GradientBoosting 为 I/E、N/S、F/T、J/P 四个维度分别训练二分类器，
并导出模型、scaler 与评估报告。

当真实样本 >= 50 时自动切换到 GradientBoosting 并启用交叉验证超参搜索。
"""

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, GridSearchCV
from sklearn.preprocessing import StandardScaler

from mbti_features import FEATURE_COLS, DIMENSIONS

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data" / "mbti_training"
MODEL_DIR = PROJECT_ROOT / "web" / "models"

# 切换到 GradientBoosting 的真实样本阈值
GB_MIN_REAL_SAMPLES = 50


def load_data(csv_path: Path) -> tuple[np.ndarray, dict[str, np.ndarray], pd.DataFrame]:
    """加载 CSV，并拆成特征矩阵与四个维度标签。"""
    df = pd.read_csv(csv_path)
    X = df[FEATURE_COLS].apply(pd.to_numeric, errors="coerce").values

    y: dict[str, np.ndarray] = {}
    for index, dim in enumerate(DIMENSIONS):
        y[dim] = np.array([
            1 if mbti[index] == dim[1] else 0
            for mbti in df["mbti"].str.upper()
        ])
    return X, y, df


def train_models(
    X_train: np.ndarray,
    y_train: dict[str, np.ndarray],
    n_estimators: int = 100,
    use_gb: bool = False,
) -> dict[str, RandomForestClassifier | GradientBoostingClassifier]:
    """为每个维度训练分类器。

    use_gb=True 时使用 GradientBoosting + GridSearchCV，
    否则使用 Random Forest。
    """
    models: dict[str, object] = {}
    for dim in DIMENSIONS:
        print(f"\n训练 {dim} 分类器 ({'GradientBoosting' if use_gb else 'RandomForest'})...")
        class_counts = np.bincount(y_train[dim], minlength=2)
        print(f"  类别分布: {class_counts.tolist()}")

        if use_gb and class_counts.min() >= 10:
            # GradientBoosting + 超参搜索
            param_grid = {
                "n_estimators": [50, 100, 200],
                "max_depth": [3, 5, 7],
                "learning_rate": [0.05, 0.1, 0.2],
                "min_samples_leaf": [3, 5],
            }
            base_clf = GradientBoostingClassifier(random_state=42)
            effective_folds = min(3, int(class_counts.min()))
            if effective_folds >= 2:
                cv = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)
                grid = GridSearchCV(
                    base_clf, param_grid, cv=cv, scoring="accuracy",
                    n_jobs=-1, refit=True,
                )
                grid.fit(X_train, y_train[dim])
                clf = grid.best_estimator_
                print(f"  最优参数: {grid.best_params_}")
                print(f"  CV Accuracy: {grid.best_score_:.3f}")
            else:
                clf = GradientBoostingClassifier(
                    n_estimators=100, max_depth=5, learning_rate=0.1,
                    min_samples_leaf=5, random_state=42,
                )
                clf.fit(X_train, y_train[dim])
        else:
            # Random Forest
            max_depth = 8 if class_counts.min() >= 20 else 5
            min_leaf = 5 if class_counts.min() >= 30 else 3
            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_leaf=min_leaf,
                class_weight="balanced",
                random_state=42,
            )
            clf.fit(X_train, y_train[dim])

        models[dim] = clf

        importances = clf.feature_importances_
        top_indices = np.argsort(importances)[-5:][::-1]
        print("  重要特征 Top 5:")
        for feature_index in top_indices:
            print(
                f"    {FEATURE_COLS[feature_index]}: {importances[feature_index]:.3f}")
    return models


def evaluate_models(
    models: dict[str, RandomForestClassifier],
    X_test: np.ndarray,
    y_test: dict[str, np.ndarray],
) -> dict:
    """在测试集上评估每个维度。"""
    results = {}
    for dim in DIMENSIONS:
        y_true = y_test[dim]
        class_counts = np.bincount(y_true, minlength=2)
        if class_counts.min() == 0:
            results[dim] = {
                "not_evaluable": True,
                "reason": "测试集只有单一类别，无法判断模型是否真的学会该维度",
                "class_counts": class_counts.tolist(),
                "support": int(y_true.sum()),
            }
            print(f"\n{dim}: not_evaluable (测试集单类)")
            continue

        y_pred = models[dim].predict(X_test)
        results[dim] = {
            "accuracy": accuracy_score(y_true, y_pred),
            "precision": precision_score(y_true, y_pred, zero_division=0),
            "recall": recall_score(y_true, y_pred, zero_division=0),
            "f1": f1_score(y_true, y_pred, zero_division=0),
            "support": int(y_true.sum()),
        }
        print(f"\n{dim}:")
        print(f"  Accuracy:  {results[dim]['accuracy']:.3f}")
        print(f"  Precision: {results[dim]['precision']:.3f}")
        print(f"  Recall:    {results[dim]['recall']:.3f}")
        print(f"  F1:        {results[dim]['f1']:.3f}")
        print(
            f"  分类报告:\n{classification_report(y_true, y_pred, zero_division=0)}")
    return results


def cross_validate(X: np.ndarray, y: dict[str, np.ndarray], n_folds: int = 5) -> dict:
    """交叉验证评估。"""
    results = {}

    for dim in DIMENSIONS:
        class_counts = np.bincount(y[dim])
        if len(class_counts) < 2 or class_counts.min() < 2:
            results[dim] = {
                "skipped": True,
                "reason": "某一类别样本不足，无法做可靠交叉验证",
                "class_counts": class_counts.tolist(),
            }
            print(f"{dim} CV: skipped (类别覆盖不足)")
            continue

        effective_folds = min(n_folds, int(class_counts.min()))
        if effective_folds < 2:
            results[dim] = {
                "skipped": True,
                "reason": "最少类别样本 < 2，无法做交叉验证",
                "class_counts": class_counts.tolist(),
            }
            print(f"{dim} CV: skipped (最少类别样本 < 2)")
            continue

        cv = StratifiedKFold(
            n_splits=effective_folds,
            shuffle=True,
            random_state=42,
        )
        clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
        )
        scores = cross_val_score(clf, X, y[dim], cv=cv, scoring="accuracy")
        results[dim] = {
            "cv_accuracy_mean": scores.mean(),
            "cv_accuracy_std": scores.std(),
            "cv_scores": scores.tolist(),
            "n_folds": effective_folds,
            "class_counts": class_counts.tolist(),
        }
        print(
            f"{dim} CV: {scores.mean():.3f} +/- {scores.std():.3f} (folds={effective_folds})")

    return results


def build_dimension_summary(y_values: np.ndarray) -> dict:
    """汇总一个维度的类别分布。"""
    counts = np.bincount(y_values, minlength=2)
    return {
        "negative_class": int(counts[0]),
        "positive_class": int(counts[1]),
        "evaluatable": bool(counts.min() > 0),
    }


def export_models(
    models: dict[str, object],
    imputer: SimpleImputer,
    scaler: StandardScaler,
    output_dir: Path,
    n_train_real: int = 0,
    model_type: str = "rf",
):
    """导出模型与 scaler。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    model_path = output_dir / "mbti_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(
            {
                "models": models,
                "dimensions": DIMENSIONS,
                "feature_columns": FEATURE_COLS,
                "version": "3.0",
                "model_type": model_type,
                "n_train_real": n_train_real,
                "imputer_statistics": imputer.statistics_.tolist(),
            },
            f,
        )
    print(f"模型已保存: {model_path} (type={model_type}, real={n_train_real})")

    scaler_path = output_dir / "scaler.pkl"
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    print(f"Scaler 已保存: {scaler_path}")


def main():
    parser = argparse.ArgumentParser(description="MBTI 模型训练")
    parser.add_argument("--n-estimators", type=int,
                        default=100, help="Random Forest 树数量")
    parser.add_argument("--no-cv", action="store_true", help="跳过交叉验证")
    parser.add_argument("--model", choices=["auto", "rf", "gb"],
                        default="auto", help="模型类型: auto=自动, rf=RandomForest, gb=GradientBoosting")
    args = parser.parse_args()

    train_path = DATA_DIR / "split" / "train.csv"
    test_path = DATA_DIR / "split" / "test.csv"
    if not train_path.exists():
        print(f"未找到训练数据: {train_path}")
        print("请先运行: python build_mbti_dataset.py + python augment_mbti_data.py")
        sys.exit(1)

    X_train, y_train, train_df = load_data(train_path)
    X_test, y_test, test_df = load_data(test_path)

    # 计算真实样本数（排除合成样本）
    n_train_real = int((~train_df["user_id"].str.startswith("syn_")).sum())
    print(f"训练集: {X_train.shape[0]} 样本 (真实: {n_train_real})")
    print(f"测试集: {X_test.shape[0]} 样本")

    # 自动选择模型类型
    if args.model == "auto":
        use_gb = n_train_real >= GB_MIN_REAL_SAMPLES
        model_type = "gb" if use_gb else "rf"
        print(f"自动选择: {model_type} (真实样本 {n_train_real} {'≥' if use_gb else '<'} {GB_MIN_REAL_SAMPLES})")
    elif args.model == "gb":
        use_gb = True
        model_type = "gb"
    else:
        use_gb = False
        model_type = "rf"

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(imputer.fit_transform(X_train))
    X_test_scaled = scaler.transform(imputer.transform(X_test))

    if not args.no_cv:
        print("\n=== 交叉验证 ===")
        cv_results = cross_validate(X_train_scaled, y_train)
    else:
        cv_results = None

    print("\n=== 训练模型 ===")
    models = train_models(X_train_scaled, y_train,
                          n_estimators=args.n_estimators,
                          use_gb=use_gb)

    print("\n=== 测试集评估 ===")
    eval_results = evaluate_models(models, X_test_scaled, y_test)

    export_models(models, imputer, scaler, MODEL_DIR,
                  n_train_real=n_train_real,
                  model_type=model_type)

    report = {
        "train_samples": X_train.shape[0],
        "train_real_samples": n_train_real,
        "test_samples": X_test.shape[0],
        "model_type": model_type,
        "n_estimators": args.n_estimators,
        "dimensions": eval_results,
        "train_mbti_distribution": train_df["mbti"].value_counts().to_dict(),
        "test_mbti_distribution": test_df["mbti"].value_counts().to_dict(),
        "dimension_coverage": {
            dim: {
                "train": build_dimension_summary(y_train[dim]),
                "test": build_dimension_summary(y_test[dim]),
            }
            for dim in DIMENSIONS
        },
    }
    if cv_results is not None:
        report["cross_validation"] = cv_results

    report_path = DATA_DIR / "evaluation.json"
    report_path.write_text(json.dumps(
        report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n评估报告: {report_path}")


if __name__ == "__main__":
    main()
