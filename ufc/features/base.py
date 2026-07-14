"""Base class for all feature engineering modules.

This design allows polymorphic usage so each feature category
can be developed, tested, and run independently.
"""

from abc import ABC, abstractmethod
from typing import List
import pandas as pd


class FeatureEngineer(ABC):
    """Abstract base class for feature engineering modules."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute and add new feature columns to the input DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Input dataframe (usually the joined complete dataset)

        Returns
        -------
        pd.DataFrame
            DataFrame with new feature columns added.
        """
        pass

    @property
    def feature_names(self) -> List[str]:
        """Return the list of feature names this module produces."""
        return []

    def __repr__(self):
        return f"{self.__class__.__name__}(features={self.feature_names})"
