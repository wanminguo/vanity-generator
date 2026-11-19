# -*- coding: utf-8 -*-
"""
极简 OpenCL 封装（ctypes 直调 OpenCL.dll，零第三方依赖）

只用得到的一小部分：
  平台/设备枚举 -> context -> queue -> 运行时编译内核 -> buffer -> NDRange

内核源码在运行时交给驱动编译（NVIDIA 的 OpenCL 平台自带 PTX 编译器），
所以不需要安装 CUDA Toolkit、不需要 cl.exe、不需要任何预先构建的二进制。

说明：本文件不联网、不下载任何东西。
"""

import ctypes as C
import os
import sys

cl_uint = C.c_uint
cl_int = C.c_int
cl_ulong = C.c_ulonglong
cl_bool = C.c_uint
size_t = C.c_size_t
c_void_p = C.c_void_p

# ---- 常量
CL_SUCCESS = 0
CL_DEVICE_TYPE_GPU = 1 << 2
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF
CL_MEM_READ_WRITE = 1 << 0
CL_MEM_WRITE_ONLY = 1 << 1
CL_MEM_READ_ONLY = 1 << 2
CL_MEM_COPY_HOST_PTR = 1 << 5
CL_TRUE, CL_FALSE = 1, 0

PLATFORM_NAME = 0x0902
PLATFORM_VENDOR = 0x0903
PLATFORM_VERSION = 0x0901
DEVICE_NAME = 0x102B
DEVICE_MAX_CU = 0x1002
DEVICE_GLOBAL_MEM = 0x101F
DEVICE_MAX_WG = 0x1004
DEVICE_CLOCK = 0x100C
DEVICE_MAX_MEM_ALLOC = 0x1010
PROGRAM_BUILD_LOG = 0x1181


class OpenCLError(RuntimeError):
    pass


_lib = None


def lib():
    """延迟加载 OpenCL.dll；不存在则抛出可读错误"""
    global _lib
    if _lib is not None:
        return _lib

    names = ["OpenCL.dll", "OpenCL.dll"]
    last = None
    for n in names:
        try:
            _lib = C.CDLL(n)
            break
        except OSError as exc:
            last = exc
    if _lib is None:
        raise OpenCLError(f"系统里找不到 OpenCL.dll：{last}")

    # 所有函数必须显式声明签名，否则 64 位指针会被截断成 32 位而崩溃
    _lib.clGetPlatformIDs.argtypes = [cl_uint, C.POINTER(c_void_p), C.POINTER(cl_uint)]
    _lib.clGetPlatformIDs.restype = cl_int

    _lib.clGetPlatformInfo.argtypes = [c_void_p, cl_uint, size_t, c_void_p, C.POINTER(size_t)]
    _lib.clGetPlatformInfo.restype = cl_int

    _lib.clGetDeviceIDs.argtypes = [c_void_p, cl_uint, cl_uint,
                                    C.POINTER(c_void_p), C.POINTER(cl_uint)]
    _lib.clGetDeviceIDs.restype = cl_int

    _lib.clGetDeviceInfo.argtypes = [c_void_p, cl_uint, size_t, c_void_p, C.POINTER(size_t)]
    _lib.clGetDeviceInfo.restype = cl_int

    _lib.clCreateContext.argtypes = [C.c_void_p, cl_uint, C.POINTER(c_void_p),
                                     c_void_p, c_void_p, C.POINTER(cl_int)]
    _lib.clCreateContext.restype = c_void_p

    _lib.clReleaseContext.argtypes = [c_void_p]
    _lib.clReleaseContext.restype = cl_int

    _lib.clCreateCommandQueue.argtypes = [c_void_p, c_void_p, cl_uint, C.POINTER(cl_int)]
    _lib.clCreateCommandQueue.restype = c_void_p

    _lib.clReleaseCommandQueue.argtypes = [c_void_p]
    _lib.clReleaseCommandQueue.restype = cl_int

    _lib.clCreateProgramWithSource.argtypes = [c_void_p, cl_uint, C.POINTER(C.c_char_p),
                                               C.POINTER(size_t), C.POINTER(cl_int)]
    _lib.clCreateProgramWithSource.restype = c_void_p

    _lib.clBuildProgram.argtypes = [c_void_p, cl_uint, C.POINTER(c_void_p), C.c_char_p,
                                    c_void_p, c_void_p]
    _lib.clBuildProgram.restype = cl_int

    _lib.clGetProgramBuildInfo.argtypes = [c_void_p, c_void_p, cl_uint, size_t,
                                           c_void_p, C.POINTER(size_t)]
    _lib.clGetProgramBuildInfo.restype = cl_int

    _lib.clCreateKernel.argtypes = [c_void_p, C.c_char_p, C.POINTER(cl_int)]
    _lib.clCreateKernel.restype = c_void_p

    _lib.clReleaseProgram.argtypes = [c_void_p]
    _lib.clReleaseKernel.argtypes = [c_void_p]

    _lib.clCreateBuffer.argtypes = [c_void_p, C.c_ulong, size_t, c_void_p, C.POINTER(cl_int)]
    _lib.clCreateBuffer.restype = c_void_p

    _lib.clReleaseMemObject.argtypes = [c_void_p]

    _lib.clSetKernelArg.argtypes = [c_void_p, cl_uint, size_t, c_void_p]
    _lib.clSetKernelArg.restype = cl_int

    _lib.clEnqueueWriteBuffer.argtypes = [c_void_p, c_void_p, cl_bool, size_t, size_t,
                                          c_void_p, cl_uint, C.POINTER(c_void_p), c_void_p]
    _lib.clEnqueueWriteBuffer.restype = cl_int

    _lib.clEnqueueReadBuffer.argtypes = [c_void_p, c_void_p, cl_bool, size_t, size_t,
                                         c_void_p, cl_uint, C.POINTER(c_void_p), c_void_p]
    _lib.clEnqueueReadBuffer.restype = cl_int

    _lib.clEnqueueNDRangeKernel.argtypes = [c_void_p, c_void_p, cl_uint,
                                            C.POINTER(size_t), C.POINTER(size_t),
                                            C.POINTER(size_t), cl_uint,
                                            C.POINTER(c_void_p), c_void_p]
    _lib.clEnqueueNDRangeKernel.restype = cl_int

    _lib.clFinish.argtypes = [c_void_p]
    _lib.clFinish.restype = cl_int

    _lib.clFlush.argtypes = [c_void_p]
    _lib.clFlush.restype = cl_int
    return _lib


def _check(ret, what):
    if ret != CL_SUCCESS:
        raise OpenCLError(f"{what} 失败，错误码 {ret}")
    return ret


def _info_str(handle, param, getter):
    buf = C.create_string_buffer(512)
    getter(handle, param, 512, buf, None)
    return buf.value.decode("utf-8", "replace").strip()


def _info_int(handle, param, getter, typ=cl_uint, size=4):
    v = typ(0)
    l = lib()
    getter(handle, param, size, C.byref(v), None)
    return v.value


def list_devices():
    """返回 [{platform, vendor, device, cu, mem_mb, max_wg, clock_mhz}]，只列 GPU 设备"""
    l = lib()
    n = cl_uint(0)
    ret = l.clGetPlatformIDs(0, None, C.byref(n))
    if ret != CL_SUCCESS or n.value == 0:
        return []

    PIDs = c_void_p * n.value
    pids = PIDs()
    l.clGetPlatformIDs(n.value, pids, None)

    out = []
    for pid in pids:
        pl_name = _info_str(pid, PLATFORM_NAME, l.clGetPlatformInfo)
        pl_vendor = _info_str(pid, PLATFORM_VENDOR, l.clGetPlatformInfo)

        dn = cl_uint(0)
        if l.clGetDeviceIDs(pid, CL_DEVICE_TYPE_GPU, 0, None, C.byref(dn)) != CL_SUCCESS or dn.value == 0:
            continue
        DIDs = c_void_p * dn.value
        dids = DIDs()
        l.clGetDeviceIDs(pid, CL_DEVICE_TYPE_GPU, dn.value, dids, None)

        for did in dids:
            out.append({
                "platform": pl_name,
                "vendor": pl_vendor,
                "_pid": pid,
                "_did": did,
                "device": _info_str(did, DEVICE_NAME, l.clGetDeviceInfo),
                "cu": _info_int(did, DEVICE_MAX_CU, l.clGetDeviceInfo),
                "mem_mb": _info_int(did, DEVICE_GLOBAL_MEM, l.clGetDeviceInfo, cl_ulong, 8) // (1024 * 1024),
                "max_wg": _info_int(did, DEVICE_MAX_WG, l.clGetDeviceInfo, size_t, 8),
                "clock_mhz": _info_int(did, DEVICE_CLOCK, l.clGetDeviceInfo),
                "max_alloc_mb": _info_int(did, DEVICE_MAX_MEM_ALLOC, l.clGetDeviceInfo, cl_ulong, 8) // (1024 * 1024),
            })
    return out


class Device:
    """一个 GPU 上的 context + queue，加上编译好的内核"""

    def __init__(self, dev_info=None, log=None):
        l = lib()
        if dev_info is None:
            devs = list_devices()
            if not devs:
                raise OpenCLError("没有找到可用的 GPU（OpenCL 设备）")
            dev_info = devs[0]
        self.info = dev_info
        self._log = log or (lambda m: None)

        pid = dev_info["_pid"]
        did = dev_info["_did"]

        err = cl_int(0)
        self.ctx = l.clCreateContext(None, 1, C.byref(C.c_void_p(did)), None, None, C.byref(err))
        _check(err.value, "创建 OpenCL context")
        if not self.ctx:
            raise OpenCLError("创建 OpenCL context 返回空")

        self.queue = l.clCreateCommandQueue(self.ctx, C.c_void_p(did), 0, C.byref(err))
        _check(err.value, "创建命令队列")

        self.kernels = {}
        self.buffers = {}

    # ---- 内核

    def build(self, source, kernel_names, options=b"-cl-fast-relaxed-math"):
        l = lib()
        src = C.c_char_p(source.encode("utf-8"))
        err = cl_int(0)
        program = l.clCreateProgramWithSource(self.ctx, 1, C.byref(src), None, C.byref(err))
        _check(err.value, "创建 program")

        ret = l.clBuildProgram(program, 1, C.byref(C.c_void_p(self.info["_did"])),
                               options, None, None)
        if ret != CL_SUCCESS:
            log_buf = C.create_string_buffer(16384)
            l.clGetProgramBuildInfo(program, C.c_void_p(self.info["_did"]), PROGRAM_BUILD_LOG,
                                    16384, log_buf, None)
            raise OpenCLError("内核编译失败：\n" + log_buf.value.decode("utf-8", "replace"))

        for name in kernel_names:
            k = l.clCreateKernel(program, name.encode(), C.byref(err))
            _check(err.value, f"创建 kernel {name}")
            self.kernels[name] = k
        l.clReleaseProgram(program)
        return self

    def buffer(self, name, size, flags=CL_MEM_READ_WRITE, host=None):
        l = lib()
        err = cl_int(0)
        host_ptr = None
        if host is not None:
            host_ptr = C.cast(host, c_void_p)
            flags |= CL_MEM_COPY_HOST_PTR
        mem = l.clCreateBuffer(self.ctx, C.c_ulong(flags), size, host_ptr, C.byref(err))
        _check(err.value, f"分配显存 {name}（size={size}, flags={flags}）")
        self.buffers[name] = mem
        return mem

    def write(self, name, size, host_ptr):
        l = lib()
        _check(l.clEnqueueWriteBuffer(self.queue, self.buffers[name], CL_TRUE, 0, size,
                                      C.cast(host_ptr, c_void_p), 0, None, None),
               f"写入 {name}")

    def read(self, name, size, host_ptr):
        l = lib()
        _check(l.clEnqueueReadBuffer(self.queue, self.buffers[name], CL_TRUE, 0, size,
                                     C.cast(host_ptr, c_void_p), 0, None, None),
               f"读回 {name}")

    def run(self, kernel, global_size, local_size, args):
        """
        args: [(size_bytes, ptr_or_None_for_buffer, bufname_or_None), ...]
              buffer 参数写成 (bufname,)；标量写成 (size, byref(value))
        """
        l = lib()
        k = self.kernels[kernel]
        for i, a in enumerate(args):
            if isinstance(a, tuple) and len(a) == 1:
                _check(l.clSetKernelArg(k, i, C.sizeof(c_void_p),
                                        C.byref(C.c_void_p(self.buffers[a[0]])),
                                        ), f"设置参数 {kernel}#{i}")
            else:
                size, ptr = a
                _check(l.clSetKernelArg(k, i, size, ptr), f"设置参数 {kernel}#{i}")

        gsz = (size_t * 1)(global_size)
        lsz = (size_t * 1)(local_size) if local_size else None
        _check(l.clEnqueueNDRangeKernel(self.queue, k, 1, None, gsz,
                                        lsz if lsz else None, 0, None, None),
               f"执行 {kernel}")

    def finish(self):
        _check(lib().clFinish(self.queue), "等待 GPU 完成")

    # ---- 清理

    def release(self):
        l = lib()
        for k in self.kernels.values():
            if k:
                l.clReleaseKernel(k)
        for b in self.buffers.values():
            if b:
                l.clReleaseMemObject(b)
        if self.queue:
            l.clReleaseCommandQueue(self.queue)
        if self.ctx:
            l.clReleaseContext(self.ctx)
        self.kernels.clear()
        self.buffers.clear()

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


if __name__ == "__main__":
    for d in list_devices():
        print(f"{d['platform']} / {d['device']}  CU={d['cu']}  "
              f"{d['mem_mb']}MB  maxWG={d['max_wg']}  {d['clock_mhz']}MHz")
