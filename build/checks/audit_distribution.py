"""Verify source, packaged bytecode, board agent, wheel, and runtime data agree."""
import ast
import json
from pathlib import Path
import zipfile
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[2]


def main():
    app = ROOT / 'build/dist/desktop/ZynqBjtDesktop'
    source = ROOT / 'src/python'
    agent_count = 0
    with zipfile.ZipFile(app / '_internal/agent.pyz') as archive:
        for name in archive.namelist():
            if name.startswith('zynq_bjt/') and name.endswith('.py'):
                data = archive.read(name)
                assert data == (source / name).read_bytes(), name
                ast.parse(data.decode('utf-8-sig'), feature_version=(3, 8))
                agent_count += 1
    exe = CArchiveReader(str(app / 'ZynqBjtDesktop.exe'))
    pyz = exe.open_embedded_archive('PYZ.pyz')
    compiled = []
    for path in (source / 'zynq_bjt').glob('*.py'):
        module = 'zynq_bjt' + ('' if path.stem == '__init__' else '.' + path.stem)
        if module in pyz.toc:
            code = pyz.extract(module)
            assert code == compile(path.read_bytes(), code.co_filename, 'exec', optimize=0), module
            compiled.append(module)
    assert len(compiled) >= 40
    data_count = 0
    runtime_data = app / '_internal/data'
    for path in runtime_data.rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (ROOT / 'data' / path.relative_to(runtime_data)).read_bytes(), path.name
            data_count += 1
    wheel_count = 0
    with zipfile.ZipFile(ROOT / 'board/software/zynq_bjt-0.2.0-py3-none-any.whl') as archive:
        for name in archive.namelist():
            if name.startswith('zynq_bjt/') and name.endswith('.py'):
                assert archive.read(name) == (source / name).read_bytes(), name
                wheel_count += 1
    result = dict(passed=True, board_agent_modules=agent_count,
                  python38_agent_syntax=True, compiled_modules_checked=len(compiled),
                  runtime_data_files=data_count, wheel_modules=wheel_count)
    target = ROOT / 'report/validation/source_consistency.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
