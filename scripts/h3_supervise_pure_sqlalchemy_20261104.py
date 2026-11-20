"""Task-scoped SQLAlchemy option for the reviewed existing H3 supervisor and its children."""
import os
from pathlib import Path
import runpy
import sys

from h3_persistent_supervisor_20261103 import assert_config


def main():
    here=Path(__file__).resolve()
    root=here.parents[1]
    run=root/'data/video_generation/h3_six_children_full_script_recovery_20261104'
    case=run/'validator_recovery/F0051_access_violation_resume'
    assert_config(case/'RECOVERY_PLAN.json')
    if sys.argv[1:]!=['supervise','--run',str(run)] or not (case/'APPLIED.json').is_file():
        raise ValueError('reviewed supervisor scope or activation missing')
    os.environ['DISABLE_SQLALCHEMY_CEXT_RUNTIME']='1'
    original=here.with_name('h3_restart_continuation_20261104.py')
    sys.argv[0]=str(original)
    runpy.run_path(str(original),run_name='__main__')


if __name__=='__main__':
    main()

