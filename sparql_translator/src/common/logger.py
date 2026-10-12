"""
ロガーユーティリティ
- プロジェクト直下の log/YYYY-MM-DD.log にログを出力する
- --verbose フラグでコンソールに DEBUG 情報を出す
"""
import logging
import os
from datetime import datetime


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """ロガーを取得する。ログファイルは project_root/log/YYYY-MM-DD.log に保存される

    Args:
        name (str): ロガー名
        verbose (bool): True の場合コンソールに DEBUG を出力する
    Returns:
        logging.Logger: 設定済みロガー
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # log ディレクトリ
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'log')
    os.makedirs(log_dir, exist_ok=True)

    filename = datetime.now().strftime('%Y-%m-%d') + '.log'
    file_path = os.path.join(log_dir, filename)

    fh = logging.FileHandler(file_path, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.WARNING)
    ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(ch)

    return logger
