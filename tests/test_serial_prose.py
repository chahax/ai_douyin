import pytest
from scripts.produce_serial_prose import check_coverage

def test_exact_coverage_does_not_force_fixed_episode_length():
    check_coverage([{'start':1,'end':1},{'start':2,'end':4},{'start':5,'end':6}],list(range(1,7)))

@pytest.mark.parametrize('episodes',[[{'start':1,'end':2},{'start':2,'end':3}],
    [{'start':1,'end':1},{'start':3,'end':3}], [{'start':2,'end':3},{'start':1,'end':1}],
    [{'start':1,'end':4}], [{'start':'1','end':3}]])
def test_gap_overlap_out_of_order_and_oversized_output_are_not_accepted(episodes):
    with pytest.raises(ValueError):check_coverage(episodes,[1,2,3])
