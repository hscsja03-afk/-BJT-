"""Validated, endpoint-inclusive segmented sweeps shared by the instruments."""
from decimal import Decimal, InvalidOperation


def segmented_values(spec, minimum, maximum, limit=2000):
    """Parse start:stop:step;... without evaluating user-entered code."""
    values=[]
    try:
        for segment in str(spec).replace('；',';').split(';'):
            if not segment.strip():continue
            parts=segment.replace('：',':').split(':')
            if len(parts)!=3:raise ValueError('每段须填写起点、终点、步长')
            start,stop,step=(Decimal(part.strip()) for part in parts)
            if not all(v.is_finite() for v in (start,stop,step)) or step<=0 or not Decimal(str(minimum))<=start<=stop<=Decimal(str(maximum)):
                raise ValueError('分段范围或步长无效（允许 {}～{}）'.format(minimum,maximum))
            if values and start<values[-1]:raise ValueError('分段必须递增，不能交叠或倒序')
            position=start
            while True:
                if not values or position!=values[-1]:values.append(position)
                if len(values)>limit:raise ValueError('分段扫描点数超过 {}'.format(limit))
                if position==stop:break
                position=min(position+step,stop)
    except InvalidOperation as error:
        raise ValueError('分段参数必须为有限数字') from error
    if not values:raise ValueError('至少设置一个扫描区间')
    return [float(value) for value in values]
