import os
import logging
from typing import Any, Dict, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

def expand_conversion_jobs(
    files: List[Tuple[str, str]], 
    params: Dict[str, Any]
) -> List[Tuple[str, str, Dict[str, Any], Optional[str]]]:
    """
    Expands a list of files into a list of specific conversion jobs.
    
    If auto_cutter_enabled is True, it extracts the Top N highlights for each 
    eligible long video and returns multiple jobs per input file.
    
    Returns:
        A list of tuples: (iid, src_path, job_params, output_suffix)
    """
    auto_cutter = params.get("auto_cutter_enabled", False)
    top_n = int(params.get("auto_cutter_top_n", 5))
    
    expanded_jobs = []
    
    for iid, src_path in files:
        if not auto_cutter:
            # Single standard job
            expanded_jobs.append((iid, src_path, params, None))
            continue
            
        logger.info(f"[JOB EXPANDER] Auto-Cutter enabled: scanning {Path(src_path).name} for top {top_n} highlights...")
        from src.auto_action.highlights import extract_highlights
        
        # We extract highlights using a 6s window (which covers typical GIF length + 1s padding)
        highlights = extract_highlights(src_path, top_n=top_n, window_sec=6.0, sample_fps=2.0)
        
        if not highlights:
            logger.warning(f"[JOB EXPANDER] No highlights found for {Path(src_path).name}. Yielding full file.")
            expanded_jobs.append((iid, src_path, params, None))
            continue
            
        # We found highlights! Generate one job per highlight.
        for h_idx, (start_sec, end_sec) in enumerate(highlights):
            # Deep copy params to override trim logic for this specific job
            job_params = dict(params)
            # The auto-action preprocessor uses these
            job_params["v_trim_start"] = start_sec
            job_params["v_trim_end"] = end_sec
            
            # The orchestrator might not read v_trim_start from params directly but from model,
            # so we inject it as trim_start directly.
            job_params["trim_start"] = start_sec
            job_params["trim_end"] = end_sec
            
            suffix = f"_top{h_idx + 1}" if len(highlights) > 1 else None
            expanded_jobs.append((iid, src_path, job_params, suffix))
            
    return expanded_jobs
