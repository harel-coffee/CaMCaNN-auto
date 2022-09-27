"""Linear CMC prediction model with feature selection."""
from pathlib import Path
from tokenize import Name
from typing import Dict, List, Union, NamedTuple
from sklearn.pipeline import make_pipeline
from sklearn.feature_selection import SelectFromModel
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNetCV, RidgeCV
import numpy as np

from .data.featurise.ecfp import SMILESHashes


class RidgeResults(NamedTuple):
    """Hold the results of a ridge regression models.

    Args:
        best_rmse: The best root mean squared error during training.
        alpha: The best alpha identified during training.
        coefs: The weights of each subgraph from training.
        test_rmse: The testing RMSE.

    """

    best_rmse: float
    alpha: float
    coefs: np.ndarray
    test_rmse: float

    def get_unnormed_contribs(self, scaler: StandardScaler) -> np.ndarray:
        """Get the contributions of the unnormalised subgraphs."""
        return scaler.inverse_transform(self.coefs)

    def __repr__(self) -> str:
        return (
            f"Best train RMSE: {self.best_rmse}\n"
            f"Best alpha: {self.alpha}\n"
            f"Test RMSE: {self.test_rmse}"
        )


class LinearECFPModel:
    """Get weights associated with the most important subgraphs to predict CMC."""

    def __init__(
        self,
        smiles_hashes: SMILESHashes,
        train_fps: np.ndarray,
        train_targets: np.ndarray,
        test_fps: np.ndarray,
        test_targets: np.ndarray,
    ) -> None:
        """Initialize smiles hash dataframe."""
        self.smiles_hashes = smiles_hashes
        self.train_fps = train_fps
        self.train_targets = train_targets
        self.test_fps = test_fps
        self.test_targets = test_targets

        self.scaler = StandardScaler()
        self.encv = ElasticNetCV(l1_ratio=[0.1, 0.5, 0.7, 0.9, 0.95, 0.99, 1])
        self.ridge = RidgeCV(scoring="neg_root_mean_squared_error")

    def remove_low_freq_subgraphs(self, threshold: Union[float, int] = 1) -> int:
        """Amend the smiles hashes to remove those that only occur once in the training data.

        Args:
            threshold: How many to remove. If a float, remove subgraphs that
                occur in fewer than this fraction of molecules in the training data.
                If an int, remove subgraphs that do not occur more than this
                many times.

        Returns:
            The number of subgraphs removed.

        """
        if isinstance(threshold, float):
            threshold = int(np.floor(threshold * self.train_fps.size[0]))

        has_group = self.train_fps > 0
        include_group = has_group.sum() > threshold

        self.smiles_hashes.hash_df["selected"] = include_group
        self.smiles_hashes.hash_df["above_threshold_occurance"] = include_group
        return (~include_group).sum()

    def elastic_feature_select(self) -> int:
        """Feature selection using Elastic Net CV regularisation.

        Returns:
            The number of subgraphs returned.

        """
        selection_pipeline = make_pipeline(self.scaler, self.encv)
        selection_pipeline.fit(self.train_fps, self.train_targets)
        self.selector = SelectFromModel(self.encv, threshold="mean", prefit=True)

        support = self.selector.get_support()
        self.smiles_hashes.set_regularised_selection(support)
        return (~support).sum()

    def ridge_model_train_test(self) -> RidgeResults:
        """Train and test the ridge regression model."""
        self.model = make_pipeline(self.scaler, self.selector, self.ridge)
        self.model.fit(self.train_fps, self.train_targets)
        self.test_predictions = self.model.predict(self.test_fps)
        test_rmse = np.sqrt(
            mean_squared_error(self.test_targets, self.test_predictions)
        ).item()
        self.results = RidgeResults(
            best_rmse=self.ridge.best_score_,
            alpha=self.ridge.alpha_,
            coefs=self.ridge.coef_,
            test_rmse=test_rmse,
        )
        self.smiles_hashes.set_weights(
            self.results.coefs, self.results.get_unnormed_contribs(self.selector)
        )
        return self.results

    def predict(self, fps: np.ndarray) -> np.ndarray:
        """Get an array of predictions."""
        try:
            return self.model.predict(fps)
        except AttributeError:
            raise ValueError("Must first fit model.")