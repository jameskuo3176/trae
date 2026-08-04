"""测试 parse_source_path 路径解析函数"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.qor_import import parse_source_path

passed = 0
failed = 0


def test(name, source_path, expected, **kwargs):
    global passed, failed
    try:
        result = parse_source_path(source_path, **kwargs)
        ok = True
        for k, v in expected.items():
            if result.get(k) != v:
                print(f'  FAIL [{name}] {k}: expected={v!r}, got={result.get(k)!r}')
                ok = False
        if ok:
            print(f'  PASS [{name}]')
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f'  FAIL [{name}] exception: {e}')
        failed += 1


def test_error(name, source_path, **kwargs):
    global passed, failed
    try:
        result = parse_source_path(source_path, **kwargs)
        print(f'  FAIL [{name}] expected ValueError, got {result!r}')
        failed += 1
    except ValueError as e:
        print(f'  PASS [{name}] ValueError: {e}')
        passed += 1
    except Exception as e:
        print(f'  FAIL [{name}] unexpected exception: {type(e).__name__}: {e}')
        failed += 1


# =========================================================================
# 正常路径测试
# =========================================================================
print('=== 正常路径 ===')

test(
    '标准路径 (含 top_module)',
    '/project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir/rpts/Synthesis/file',
    {
        'full_dir': '/project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir',
        'tag': 'cfg1_rundir',
        'version': 'syn_run_0804',
    },
    top_module='modulea_t',
)

test(
    '标准路径 (无 top_module, 自动去除前缀)',
    '/project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir/rpts/Synthesis/file',
    {
        'full_dir': '/project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir',
        'tag': 't_cfg1_rundir',
        'version': 'syn_run_0804',
    },
)

test(
    '不同项目: impl_run 版本模式',
    '/data/PRJ_A/flow1/impl_run_0423/main/cpu_top_ss_0p8v_25c/rpts/Placement/report.txt',
    {
        'full_dir': '/data/PRJ_A/flow1/impl_run_0423/main/cpu_top_ss_0p8v_25c',
        'tag': 'ss_0p8v_25c',
        'version': 'impl_run_0423',
    },
    top_module='cpu_top',
)

test(
    '不同项目: pr_run 版本模式',
    '/workspace/chip_b/run1/pr_run_2024/main/gpu_core_nom_1p0v/rpts/Route/report',
    {
        'full_dir': '/workspace/chip_b/run1/pr_run_2024/main/gpu_core_nom_1p0v',
        'tag': 'nom_1p0v',
        'version': 'pr_run_2024',
    },
    top_module='gpu_core',
)

test(
    '自定义 rpts_marker',
    '/home/user/proj/v1.0/main/my_module/reports/qor/summary.txt',
    {
        'full_dir': '/home/user/proj/v1.0/main/my_module',
        'tag': 'my_module',
        'version': None,
    },
    rpts_marker='/reports/',
)

test(
    '自定义 version_pattern',
    '/home/user/proj/2024Q3/main/top_module_opt1/rpts/synth/file',
    {
        'full_dir': '/home/user/proj/2024Q3/main/top_module_opt1',
        'tag': 'opt1',
        'version': '2024Q3',
    },
    top_module='top_module',
    version_pattern=r'^\d{4}Q\d$',
)

# =========================================================================
# 异常路径测试
# =========================================================================
print()
print('=== 异常路径 ===')

test_error(
    '空字符串',
    '',
)

test_error(
    'None',
    None,
)

test_error(
    '缺少 rpts 标记',
    '/some/path/without/the/required/marker/file.txt',
)

test_error(
    'rpts 在路径开头 (full_dir 为空)',
    # 构造: rpts 在开头, 前面没有内容
    '/rpts/subdir/file',
)

# =========================================================================
# 边界情况
# =========================================================================
print()
print('=== 边界情况 ===')

test(
    'tag 与 top_module 相同 (无剩余部分)',
    '/proj/syn_run_01/main/simple_module/rpts/report',
    {
        'full_dir': '/proj/syn_run_01/main/simple_module',
        'tag': 'simple_module',
        'version': 'syn_run_01',
    },
    top_module='simple_module',
)

test(
    '路径中无版本号段',
    '/data/proj/main/my_module/rpts/synth/file',
    {
        'full_dir': '/data/proj/main/my_module',
        'tag': 'my_module',
        'version': None,
    },
)

test(
    'Windows 风格路径 (反斜杠)',
    'C:\\project_dir\\Syn\\week2_run\\syn_run_0804\\main\\modulea_t_cfg1_rundir\\rpts\\Synthesis\\file',
    {
        'full_dir': 'C:\\project_dir\\Syn\\week2_run\\syn_run_0804\\main\\modulea_t_cfg1_rundir',
        'tag': 'cfg1_rundir',
        'version': 'syn_run_0804',
    },
    top_module='modulea_t',
    rpts_marker='\\rpts\\',
)

# =========================================================================
# 结果汇总
# =========================================================================
print()
print(f'=== 结果: {passed} PASS, {failed} FAIL ===')
if failed:
    sys.exit(1)