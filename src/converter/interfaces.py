from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

class IConverter(ABC):
    """Contrat de base pour convertir un fichier."""
    
    @abstractmethod
    def process(self, src_path: str, out_path: str, params: Dict[str, Any], start_s: Optional[float] = None, end_s: Optional[float] = None) -> Tuple[bool, str]:
        """Traite le fichier source et génère le fichier de sortie.
        Retourne un tuple (succès: bool, message: str).
        """
        pass

class IMetadataExtractor(ABC):
    """Contrat de base pour l'extraction de métadonnées d'une vidéo/GIF."""
    
    @abstractmethod
    def get_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Retourne les métadonnées ou None en cas d'échec."""
        pass

class IQualityScorer(ABC):
    """Contrat de base pour l'évaluation de la qualité de la conversion."""
    
    @abstractmethod
    def evaluate(self, gif_path: str) -> float:
        """Evalue un GIF (ex: 128x32) et retourne un score entre 0.0 et 100.0."""
        pass

class IBatchOrchestrator(ABC):
    """Contrat de base pour l'orchestration du traitement par lots."""
    
    @abstractmethod
    def process_folder(self, input_folder: str, output_folder: str, params: Dict[str, Any], progress_callback=None) -> List[Tuple[str, str]]:
        """Traite tous les fichiers d'un dossier. Retourne une liste de chemins générés."""
        pass
