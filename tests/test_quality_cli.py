import json

from test_quality_dataset import documents, write_pair
from neusymnav.cli import main


def test_quality_cli_is_offline(tmp_path, monkeypatch, capsys):
    import neusymnav.cli as cli
    def forbidden(): raise AssertionError('runtime imported')
    monkeypatch.setattr(cli,'_load_launcher', forbidden)
    gt,pred=write_pair(tmp_path,*documents())
    assert main(['evaluate-quality','--gt',str(gt),'--predictions',str(pred),'--out',str(tmp_path/'out')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['evidence_kind']=='synthetic'


def test_unannotated_cli_rejects_without_output(tmp_path,capsys):
    gt,pred=documents(); gt['frames'][0]['annotated']=False
    a,b=write_pair(tmp_path,gt,pred)
    assert main(['evaluate-quality','--gt',str(a),'--predictions',str(b),'--out',str(tmp_path/'out')])==1
    assert 'unannotated' in capsys.readouterr().err
    assert not (tmp_path/'out').exists()
