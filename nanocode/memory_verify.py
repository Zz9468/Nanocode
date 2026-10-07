"""Run tests in the fixed .temp process carrier; archive evidence under module Data/Test."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mirrors",action="store_true",help="Run real MySQL/Qwen integration and memory mirror tests")
    parser.add_argument("--env-file",type=Path,help="Local MySQL and model configuration for integration tests")
    args=parser.parse_args()
    if args.env_file is not None and not args.env_file.is_file():
        parser.error("--env-file must point to an existing local configuration file")
    root=Path(__file__).parents[1]
    data=root/"Package"/"AgentMemory"/"Data"/"Test"
    data.mkdir(parents=True,exist_ok=True)
    label=("mirrors_" if args.mirrors else "regression_")+uuid.uuid4().hex
    process=root/".temp"/"MemoryVerification"/label
    process.mkdir(parents=True)
    # Invalid/empty carrier fixtures are intentional inputs to scanner tests. They remain
    # temporary process state; the complete evidence archive belongs in Data/Test.
    mirror_roots=[root/"Package"/"AgentMemory"/"Test",root/"Package"/"AgentMemory"/"Vendor"/"MySqlDriver"/"Package"/"MySqlAccess"/"Test"]
    paths=[str(p) for directory in mirror_roots for p in directory.rglob("*.Test.py")] if args.mirrors else [str(root/"tests")]
    command=[sys.executable,"-m","pytest","-q","-ra","--import-mode=importlib","-o","cache_dir="+str(process/"Cache"),"--basetemp",str(process/"Fixtures"),*paths]
    home=process/"Home"
    home.mkdir()
    env={**os.environ,"NANOCODE_MEMORY_BACKEND":"json","PYTHONIOENCODING":"utf-8",
        "USERPROFILE":str(home),"HOME":str(home),"APPDATA":str(home/"AppData"/"Roaming"),"LOCALAPPDATA":str(home/"AppData"/"Local")}
    if args.env_file is not None:
        env["NANOCODE_MEMORY_ENV"] = str(args.env_file.resolve())
    result=subprocess.run(command,cwd=root,env=env,capture_output=True,encoding="utf-8",errors="replace")
    text=result.stdout+result.stderr
    name="mirror_tests.txt" if args.mirrors else "full_regression.txt"
    (data/name).write_text(text,"utf-8")
    archive=shutil.make_archive(str(data/label),"zip",process)
    (data/(label+".json")).write_text(json.dumps({"command":command,"exit_code":result.returncode,"evidence_archive":archive},indent=2),"utf-8")
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(text[-16000:])
    return result.returncode

if __name__=="__main__":
    raise SystemExit(main())
