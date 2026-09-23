"""
backup_db.py
每週備份 projector_intel.db（唯一沒有進 git 版本控制的狀態，見 MIGRATION.md）：

1. 本機留一份帶日期戳記的複本（backups/ 資料夾，只留最近幾份，*.db 已經在
   .gitignore 裡，不會被誤 commit）。
2. 壓縮後推到 GitHub 的 tmp/db-transfer 分支——跟之前手動搬資料庫用的是
   同一個分支，不會弄亂 main 分支的 commit 歷史（SQLite 檔案 delta 壓縮差，
   直接進 main 會讓 .git 一直腫，這是原本就不把 DB 放進 main 的原因）。

用法：
    python backup_db.py            # 備份（本機 + GitHub）
    python backup_db.py restore    # 從 GitHub tmp/db-transfer 分支還原
                                    # （GitHub Actions 每次執行開頭用這個，
                                    #  因為 Actions 的執行環境每次都是全新的，
                                    #  沒有本機這台電腦累積下來的 db）
"""
import shutil
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "projector_intel.db"
BACKUPS_DIR = ROOT / "backups"
KEEP_LOCAL = 8  # 本機只留最近幾份，避免無限占空間


def run(cmd, cwd=None) -> int:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.stdout and result.stdout.strip():
        print(result.stdout)
    if result.returncode != 0 and result.stderr and result.stderr.strip():
        print(result.stderr, file=sys.stderr)
    return result.returncode


def backup_local() -> bool:
    if not DB_PATH.exists():
        print(f"找不到 {DB_PATH}，略過本機備份", file=sys.stderr)
        return False

    BACKUPS_DIR.mkdir(exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    dest = BACKUPS_DIR / f"projector_intel_{stamp}.db"
    shutil.copy2(DB_PATH, dest)
    print(f"本機備份完成：{dest}")

    backups = sorted(BACKUPS_DIR.glob("projector_intel_*.db"), reverse=True)
    for old in backups[KEEP_LOCAL:]:
        old.unlink()
        print(f"刪除舊本機備份：{old}")
    return True


def backup_github() -> bool:
    if not DB_PATH.exists():
        print(f"找不到 {DB_PATH}，略過 GitHub 備份", file=sys.stderr)
        return False

    tar_path = ROOT / "projector_intel.db.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(DB_PATH, arcname="projector_intel.db")

    wt_dir = ROOT / "_db_transfer_wt"
    if wt_dir.exists():
        shutil.rmtree(wt_dir, ignore_errors=True)

    ok = True
    try:
        if run(["git", "fetch", "origin", "tmp/db-transfer"], cwd=ROOT) != 0:
            return False
        if run(["git", "worktree", "add", str(wt_dir), "origin/tmp/db-transfer"], cwd=ROOT) != 0:
            return False

        shutil.copy2(tar_path, wt_dir / "projector_intel.db.tar.gz")
        run(["git", "add", "projector_intel.db.tar.gz"], cwd=wt_dir)

        commit_rc = run(["git", "commit", "-m", f"DB backup {date.today().isoformat()}"], cwd=wt_dir)
        if commit_rc == 1:
            print("內容跟上次備份一樣，沒有新的變更")
        elif commit_rc != 0:
            ok = False

        if run(["git", "push", "origin", "HEAD:tmp/db-transfer"], cwd=wt_dir) != 0:
            ok = False
    finally:
        run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=ROOT)
        tar_path.unlink(missing_ok=True)

    return ok


def restore_from_github() -> bool:
    tar_path = ROOT / "projector_intel.db.tar.gz"
    try:
        if run(["git", "fetch", "origin", "tmp/db-transfer"], cwd=ROOT) != 0:
            return False
        if run(["git", "checkout", "origin/tmp/db-transfer", "--", "projector_intel.db.tar.gz"], cwd=ROOT) != 0:
            return False

        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(ROOT, filter="data")

        # 還原完把這個檔案從 git 索引清掉，main 分支不該多一個追蹤中的檔案
        run(["git", "restore", "--staged", "projector_intel.db.tar.gz"], cwd=ROOT)
    finally:
        tar_path.unlink(missing_ok=True)

    if not DB_PATH.exists():
        print("還原後找不到 projector_intel.db", file=sys.stderr)
        return False
    print(f"已從 GitHub tmp/db-transfer 分支還原：{DB_PATH}")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        sys.exit(0 if restore_from_github() else 1)

    local_ok = backup_local()
    github_ok = backup_github()
    if not (local_ok and github_ok):
        print("備份有部分失敗", file=sys.stderr)
        sys.exit(1)
    print("資料庫備份完成（本機 + GitHub tmp/db-transfer 分支）。")
