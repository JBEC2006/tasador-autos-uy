"""Preparación de variables para los modelos de log(precio). La usan los notebooks 02 y 03."""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CAT_TITULO = ["motor_titulo", "transmision_titulo", "combustible_titulo"]
CATS = ["marca_ag", "modelo_ag", "tipo_vendedor"] + CAT_TITULO
COLS = ["marca", "modelo", "tipo_vendedor", "antiguedad", "log_km"] + CAT_TITULO
NUM = ["antiguedad", "log_km"]


class Preparar(BaseEstimator, TransformerMixin):
    """Agrupa marcas y modelos raros, hace one-hot y (opcional) antigüedad × marca.

    Todo se calcula con los conteos del conjunto con el que se ajusta (train del fold),
    para no filtrar información de validación o test.

    - umbral: una marca o un modelo con menos avisos pasa a "otra_marca" / "<marca>|otro".
    - interaccion: si es True, agrega una columna antigüedad × marca por marca.
    - umbral_interaccion: si se da, solo las marcas con al menos esa cantidad de avisos tienen
      pendiente propia; el resto usa la pendiente común de `antiguedad`. Si es None, todas las
      marcas agrupadas tienen pendiente propia (comportamiento del notebook 02).
    """

    def __init__(self, umbral=10, interaccion=True, umbral_interaccion=None):
        self.umbral = umbral
        self.interaccion = interaccion
        self.umbral_interaccion = umbral_interaccion

    def _agrupar(self, X):
        X = X.copy()
        X["marca_ag"] = X["marca"].where(X["marca"].isin(self.marcas_), "otra_marca")
        clave = X["marca"] + "|" + X["modelo"]
        X["modelo_ag"] = clave.where(clave.isin(self.modelos_), X["marca_ag"] + "|otro")
        return X

    def fit(self, X, y=None):
        n_marca = X["marca"].value_counts()
        n_modelo = (X["marca"] + "|" + X["modelo"]).value_counts()
        self.marcas_ = set(n_marca[n_marca >= self.umbral].index)
        self.modelos_ = set(n_modelo[n_modelo >= self.umbral].index)
        Xa = self._agrupar(X)
        self.ohe_ = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(Xa[CATS])
        if self.umbral_interaccion is None:
            self.ohe_marca_ = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(
                Xa[["marca_ag"]])
        else:
            propias = sorted(n_marca[n_marca >= self.umbral_interaccion].index)
            # Con poco train (p. ej. en la curva de aprendizaje) puede no haber ninguna marca con
            # tantos avisos: entonces no hay pendientes propias y todas usan la común.
            self.ohe_marca_ = None if not propias else OneHotEncoder(
                categories=[propias], handle_unknown="ignore", sparse_output=False).fit(Xa[["marca"]])
        self.esc_ = StandardScaler().fit(self._numericas(Xa))
        return self

    def _numericas(self, Xa):
        num = Xa[NUM].to_numpy(dtype=float)
        if self.interaccion and self.ohe_marca_ is not None:
            col = "marca_ag" if self.umbral_interaccion is None else "marca"
            m = self.ohe_marca_.transform(Xa[[col]])
            num = np.hstack([num, m * Xa[["antiguedad"]].to_numpy(dtype=float)])
        return num

    def transform(self, X):
        Xa = self._agrupar(X)
        return np.hstack([self.esc_.transform(self._numericas(Xa)), self.ohe_.transform(Xa[CATS])])

    def nombres(self):
        """Nombre de cada columna de salida, en el mismo orden que transform."""
        num = list(NUM)
        if self.interaccion and self.ohe_marca_ is not None:
            num += [f"antiguedad×{c}" for c in self.ohe_marca_.categories_[0]]
        return num + list(self.ohe_.get_feature_names_out(CATS))

    def pendiente_por_unidad(self, coef):
        """Pasa los coeficientes de las numéricas a unidades originales (por año, por log-km)."""
        n = len(self.esc_.scale_)
        return dict(zip(self.nombres()[:n], coef[:n] / self.esc_.scale_))
