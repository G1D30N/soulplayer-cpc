
entry:
    ld hl,banner
    call print_str
    ld hl,ready_msg
    call print_str

main_loop:
    call newline
    ld hl,prompt_str
    call print_str
    call read_line
    ld a,(INPUT)
    cp 113
    jp z,quit
    cp 81
    jp z,quit
    call encode_input
    call run_inference
    jp main_loop

quit:
    call newline
    ld hl,quit_msg
    call print_str
    ret

print_str:
    ld a,(hl)
    or a
    ret z
    call 47962
    inc hl
    jr print_str

newline:
    ld a,13
    call 47962
    ld a,10
    call 47962
    ret

read_line:
    ld hl,36608
    ld b,0
read_line_loop:
    call 47878
    cp 13
    jr z,read_line_done
    ld c,a
    ld a,b
    cp 62
    jr nc,read_line_loop
    ld a,c
    ld (hl),a
    inc hl
    inc b
    call 47962
    jr read_line_loop
read_line_done:
    ld (hl),0
    call newline
    ret

char_to_token:
    cp 32
    jr nz,ct_not_space
    ld a,4
    ret
ct_not_space:
    cp 97
    jr c,ct_upper
    cp 123
    jr nc,ct_upper
    sub 92
    ret
ct_upper:
    cp 65
    jr c,ct_punct
    cp 91
    jr nc,ct_punct
    sub 60
    ret
ct_punct:
    cp 46
    jr nz,ct_p2
    ld a,31
    ret
ct_p2:
    cp 39
    jr nz,ct_p3
    ld a,32
    ret
ct_p3:
    cp 33
    jr nz,ct_p4
    ld a,33
    ret
ct_p4:
    cp 63
    jr nz,ct_p5
    ld a,34
    ret
ct_p5:
    cp 44
    jr nz,ct_p6
    ld a,35
    ret
ct_p6:
    cp 59
    jr nz,ct_p7
    ld a,36
    ret
ct_p7:
    cp 58
    jr nz,ct_p8
    ld a,37
    ret
ct_p8:
    cp 45
    jr nz,ct_unknown
    ld a,38
    ret
ct_unknown:
    xor a
    ret

encode_input:
    ld a,1
    ld (36560),a
    ld hl,36608
    ld de,36561
    ld b,1
enc_loop:
    ld a,(hl)
    or a
    jr z,enc_done
    push hl
    push de
    push bc
    call char_to_token
    pop bc
    pop de
    pop hl
    or a
    jr z,enc_skip
    ld (de),a
    inc de
    inc b
    ld a,b
    cp 18
    jr nc,enc_done
enc_skip:
    inc hl
    jr enc_loop
enc_done:
    ld a,1
    ld (de),a
    inc b
    ld a,b
    ld (36592),a
    call apply_bpe
    ret

apply_bpe:
    ld hl,merge_table
bpe_next:
    ld a,(hl)
    cp 255
    ret z
    ld (BPE_A),a
    inc hl
    ld a,(hl)
    ld (BPE_B),a
    inc hl
    ld a,(hl)
    ld (BPE_M),a
    inc hl
    ld (BPE_PTR),hl
    xor a
    ld (BPE_IDX),a
bpe_scan:
    ld a,(36592)
    dec a
    ld b,a
    ld a,(BPE_IDX)
    cp b
    jr nc,bpe_advance
    ld hl,36560
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    ld b,a
    ld a,(BPE_A)
    cp b
    jr nz,bpe_no_pair
    inc hl
    ld a,(hl)
    ld b,a
    ld a,(BPE_B)
    cp b
    jr nz,bpe_no_pair
    dec hl
    ld a,(BPE_M)
    ld (hl),a
    ld a,(BPE_IDX)
    inc a
    ld (BPE_SHIFT),a
bpe_shift_loop:
    ld a,(BPE_SHIFT)
    inc a
    ld c,a
    ld a,(36592)
    cp c
    jr z,bpe_shift_done
    jr c,bpe_shift_done
    ld a,(BPE_SHIFT)
    ld hl,36560
    ld e,a
    ld d,0
    add hl,de
    inc hl
    ld a,(hl)
    dec hl
    ld (hl),a
    ld hl,BPE_SHIFT
    inc (hl)
    jr bpe_shift_loop
bpe_shift_done:
    ld hl,36592
    dec (hl)
    jr bpe_scan
bpe_no_pair:
    ld hl,BPE_IDX
    inc (hl)
    jr bpe_scan
bpe_advance:
    ld hl,(BPE_PTR)
    jr bpe_next

print_token:
    ld l,a
    ld h,0
    add hl,hl
    ld de,decode_offsets
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,decode_strings
    add hl,de
    call print_str
    ret

blip:
    ld a,7
    call 47962
    ret

run_inference:
    call newline
    ld hl,cpc_str
    call print_str
    xor a
    ld (36593),a
gen_loop:
    call do_forward
    cp 3
    ret z
    cp 1
    ret z
    cp 0
    ret z
    push af
    ld hl,36560
    ld a,(36592)
    ld e,a
    ld d,0
    add hl,de
    pop af
    ld (hl),a
    push af
    ld hl,36592
    inc (hl)
    pop af
    call print_token
    call blip
    ld hl,36593
    inc (hl)
    ld a,(36593)
    cp 20
    ret nc
    ld a,(36592)
    cp 20
    ret nc
    jp gen_loop

addr_pos_stride:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,de
    ret

addr_pos_ed:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,de
    ret

head_offset:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ret

do_forward:
    xor a
    ld (POS),a
emb_loop:
    ld a,(POS)
    ld hl,36560
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    ld de,6144
    call addr_pos_ed
    ld (EMB_TP),hl
    ld a,(POS)
    ld de,10240
    call addr_pos_ed
    ld (EMB_PP),hl
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (EMB_DP),hl
    ld a,5
    ld (EMB_SH1),a
    ld a,5
    ld (EMB_SH2),a
    call embed_one
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(36592)
    cp b
    jp nz,emb_loop

    call layer_0
    call layer_1

    ld a,(36592)
    dec a
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,27776
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm

    ld hl,27808
    ld (MV_WP),hl
    ld hl,35920
    ld (MV_SP),hl
    ld hl,36304
    ld (MV_DP),hl
    ld a,128
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,6
    ld (MV_SHIFT),a
    call matvec
    ld hl,36304
    ld (ARG_PTR),hl
    call argmax
    ret

layer_0:
    xor a
    ld (POS),a
layer_0_kv_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,10880
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm
    ld a,(POS)
    ld de,33280
    call addr_pos_stride
    ld (CUR_D),hl
    ld hl,11936
    ld (MV_WP),hl
    ld hl,(CONST_XN)
    ld (MV_SP),hl
    ld hl,(CUR_D)
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    call matvec
    ld a,(POS)
    ld de,34560
    call addr_pos_stride
    ld (CUR_D),hl
    ld hl,12960
    ld (MV_WP),hl
    ld hl,(CONST_XN)
    ld (MV_SP),hl
    ld hl,(CUR_D)
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    call matvec
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_0_kv_loop

    xor a
    ld (POS),a
layer_0_att_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,10880
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm
    ld hl,10912
    ld (MV_WP),hl
    ld hl,35920
    ld (MV_SP),hl
    ld hl,36176
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    call matvec
    xor a
    ld (HEAD),a
layer_0_head_loop:
    ld a,(HEAD)
    call head_offset
    ld de,36176
    add hl,de
    ld (QP),hl
    ld hl,33280
    ld (KB),hl
    ld hl,34560
    ld (VB),hl
    ld a,(HEAD)
    call head_offset
    ld de,36240
    add hl,de
    ld (OP),hl
    ld a,(POS)
    inc a
    ld (NKEYS),a
    ld a,(HEAD)
    ld (HEAD_PARAM),a
    call attn_head
    ld hl,HEAD
    inc (hl)
    ld a,(HEAD)
    cp 4
    jp nz,layer_0_head_loop
    ld hl,13984
    ld (MV_WP),hl
    ld hl,36240
    ld (MV_SP),hl
    ld hl,36112
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    call matvec
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (RES_DST),hl
    ld hl,36112
    ld (RES_SRC),hl
    call residual_add
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_0_att_loop

    xor a
    ld (POS),a
layer_0_ffn_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,15008
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm
    ld hl,15040
    ld (MV_WP),hl
    ld hl,35920
    ld (MV_SP),hl
    ld hl,35984
    ld (MV_DP),hl
    ld a,64
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    ld hl,17088
    ld (MV_BP),hl
    call matvec_bias
    ld hl,35984
    ld (RELU_PTR),hl
    ld a,64
    ld (RELU_COUNT),a
    call relu
    ld hl,17216
    ld (MV_WP),hl
    ld hl,35984
    ld (MV_SP),hl
    ld hl,36112
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,64
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    ld hl,19264
    ld (MV_BP),hl
    call matvec_bias
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (RES_DST),hl
    ld hl,36112
    ld (RES_SRC),hl
    call residual_add
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_0_ffn_loop
    ret

layer_1:
    xor a
    ld (POS),a
layer_1_kv_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,19328
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm
    ld a,(POS)
    ld de,33280
    call addr_pos_stride
    ld (CUR_D),hl
    ld hl,20384
    ld (MV_WP),hl
    ld hl,(CONST_XN)
    ld (MV_SP),hl
    ld hl,(CUR_D)
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    call matvec
    ld a,(POS)
    ld de,34560
    call addr_pos_stride
    ld (CUR_D),hl
    ld hl,21408
    ld (MV_WP),hl
    ld hl,(CONST_XN)
    ld (MV_SP),hl
    ld hl,(CUR_D)
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    call matvec
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_1_kv_loop

    xor a
    ld (POS),a
layer_1_att_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,19328
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,6
    ld (RMS_SG),a
    call rms_norm
    ld hl,19360
    ld (MV_WP),hl
    ld hl,35920
    ld (MV_SP),hl
    ld hl,36176
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    call matvec
    xor a
    ld (HEAD),a
layer_1_head_loop:
    ld a,(HEAD)
    call head_offset
    ld de,36176
    add hl,de
    ld (QP),hl
    ld hl,33280
    ld (KB),hl
    ld hl,34560
    ld (VB),hl
    ld a,(HEAD)
    call head_offset
    ld de,36240
    add hl,de
    ld (OP),hl
    ld a,(POS)
    inc a
    ld (NKEYS),a
    ld a,(HEAD)
    ld (HEAD_PARAM),a
    call attn_head
    ld hl,HEAD
    inc (hl)
    ld a,(HEAD)
    cp 4
    jp nz,layer_1_head_loop
    ld hl,22432
    ld (MV_WP),hl
    ld hl,36240
    ld (MV_SP),hl
    ld hl,36112
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,8
    ld (MV_SHIFT),a
    call matvec
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (RES_DST),hl
    ld hl,36112
    ld (RES_SRC),hl
    call residual_add
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_1_att_loop

    xor a
    ld (POS),a
layer_1_ffn_loop:
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,23456
    ld (RMS_GP),hl
    ld hl,35920
    ld (RMS_DP),hl
    ld a,5
    ld (RMS_SG),a
    call rms_norm
    ld hl,23488
    ld (MV_WP),hl
    ld hl,35920
    ld (MV_SP),hl
    ld hl,35984
    ld (MV_DP),hl
    ld a,64
    ld (MV_ROWS),a
    ld a,32
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    ld hl,25536
    ld (MV_BP),hl
    call matvec_bias
    ld hl,35984
    ld (RELU_PTR),hl
    ld a,64
    ld (RELU_COUNT),a
    call relu
    ld hl,25664
    ld (MV_WP),hl
    ld hl,35984
    ld (MV_SP),hl
    ld hl,36112
    ld (MV_DP),hl
    ld a,32
    ld (MV_ROWS),a
    ld a,64
    ld (MV_COLS),a
    ld a,7
    ld (MV_SHIFT),a
    ld hl,27712
    ld (MV_BP),hl
    call matvec_bias
    ld a,(POS)
    ld de,32000
    call addr_pos_stride
    ld (RES_DST),hl
    ld hl,36112
    ld (RES_SRC),hl
    call residual_add
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,(SLEN)
    cp b
    jp nz,layer_1_ffn_loop
    ret


embed_one:
    xor a
    ld (RMS_COUNT),a
embed_loop:
    ld hl,(EMB_TP)
    ld a,(hl)
    inc hl
    ld (EMB_TP),hl
    ld (TMP),a
    or a
    jp p,emb_te_pos
    ld a,255
    jr emb_te_hi
emb_te_pos:
    xor a
emb_te_hi:
    ld (TMP+1),a
    ld a,8
    ld b,a
    ld a,(EMB_SH1)
    ld c,a
    ld a,b
    sub c
    ld b,a
    call shl_tmp_b
    ld hl,(EMB_PP)
    ld a,(hl)
    inc hl
    ld (EMB_PP),hl
    ld (SRC16),a
    or a
    jp p,emb_pe_pos
    ld a,255
    jr emb_pe_hi
emb_pe_pos:
    xor a
emb_pe_hi:
    ld (SRC16+1),a
    ld a,8
    ld b,a
    ld a,(EMB_SH2)
    ld c,a
    ld a,b
    sub c
    ld b,a
    call shl_src_b
    ld hl,(TMP)
    ld de,(SRC16)
    add hl,de
    ex de,hl
    ld hl,(EMB_DP)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (EMB_DP),hl
    ld hl,RMS_COUNT
    inc (hl)
    ld a,(RMS_COUNT)
    cp 32
    jp nz,embed_loop
    ret

shl_tmp_b:
    ld a,b
    or a
    ret z
shl_tmp_loop:
    ld hl,TMP
    sla (hl)
    inc hl
    rl (hl)
    djnz shl_tmp_loop
    ret

shl_src_b:
    ld a,b
    or a
    ret z
shl_src_loop:
    ld hl,SRC16
    sla (hl)
    inc hl
    rl (hl)
    djnz shl_src_loop
    ret

clear_acc32:
    ld hl,0
    ld (ACC32),hl
    ld (ACC32+2),hl
    ret

clear_t32:
    ld hl,0
    ld (T32),hl
    ld (T32+2),hl
    ret

clear_prod:
    ld hl,0
    ld (PROD),hl
    ld (PROD+2),hl
    ret

smul16:
    xor a
    ld (SIGN),a
    ld a,(TMP+1)
    or a
    jp p,sm16_a_pos
    call neg_tmp
    ld a,1
    ld (SIGN),a
sm16_a_pos:
    ld a,(SRC16+1)
    or a
    jp p,sm16_b_pos
    call neg_src
    ld a,(SIGN)
    xor 1
    ld (SIGN),a
sm16_b_pos:
    call clear_prod
    ld b,16
sm16_loop:
    ld hl,PROD
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,TMP
    sla (hl)
    inc hl
    rl (hl)
    jr nc,sm16_skip_add
    ld hl,(PROD)
    ld de,(SRC16)
    add hl,de
    ld (PROD),hl
    ld hl,(PROD+2)
    ld de,0
    adc hl,de
    ld (PROD+2),hl
sm16_skip_add:
    djnz sm16_loop
    ld a,(SIGN)
    or a
    ret z
    call neg_prod
    ret

neg_tmp:
    ld hl,TMP
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    ld a,(hl)
    cpl
    ld (hl),a
    ld hl,(TMP)
    inc hl
    ld (TMP),hl
    ret

neg_src:
    ld hl,SRC16
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    ld a,(hl)
    cpl
    ld (hl),a
    ld hl,(SRC16)
    inc hl
    ld (SRC16),hl
    ret

neg_prod:
    ld hl,PROD
    ld b,4
neg_prod_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_prod_cpl
    ld hl,(PROD)
    inc hl
    ld (PROD),hl
    ld a,h
    or l
    ret nz
    ld hl,(PROD+2)
    inc hl
    ld (PROD+2),hl
    ret

neg_t32:
    ld hl,T32
    ld b,4
neg_t32_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_t32_cpl
    ld hl,(T32)
    inc hl
    ld (T32),hl
    ld a,h
    or l
    ret nz
    ld hl,(T32+2)
    inc hl
    ld (T32+2),hl
    ret

neg_scra:
    ld hl,SCR_A
    ld b,4
neg_scra_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_scra_cpl
    ld hl,(SCR_A)
    inc hl
    ld (SCR_A),hl
    ld a,h
    or l
    ret nz
    ld hl,(SCR_A+2)
    inc hl
    ld (SCR_A+2),hl
    ret

add_prod_to_acc32:
    ld hl,(ACC32)
    ld de,(PROD)
    add hl,de
    ld (ACC32),hl
    ld hl,(ACC32+2)
    ld de,(PROD+2)
    adc hl,de
    ld (ACC32+2),hl
    ret

add_prod_to_t32:
    ld hl,(T32)
    ld de,(PROD)
    add hl,de
    ld (T32),hl
    ld hl,(T32+2)
    ld de,(PROD+2)
    adc hl,de
    ld (T32+2),hl
    ret

copy_acc_to_prod:
    ld hl,(ACC32)
    ld (PROD),hl
    ld hl,(ACC32+2)
    ld (PROD+2),hl
    ret

copy_t32_to_prod:
    ld hl,(T32)
    ld (PROD),hl
    ld hl,(T32+2)
    ld (PROD+2),hl
    ret

copy_scra_to_prod:
    ld hl,(SCR_A)
    ld (PROD),hl
    ld hl,(SCR_A+2)
    ld (PROD+2),hl
    ret

asr_prod_b:
    ld a,b
    or a
    ret z
asr_prod_loop:
    ld hl,PROD+3
    ld a,(hl)
    rlca
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz asr_prod_loop
    ret

lsr_acc32_b:
    ld a,b
    or a
    ret z
lsr_acc_loop:
    ld hl,ACC32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz lsr_acc_loop
    ret

sat_prod_hl:
    ld a,(PROD+3)
    or a
    jp m,sat_neg_chk
    ld a,(PROD+3)
    or a
    jr nz,sat_pos
    ld a,(PROD+2)
    or a
    jr nz,sat_pos
    ld a,(PROD+1)
    or a
    jp m,sat_pos
    ld hl,(PROD)
    ret
sat_pos:
    ld hl,32767
    ret
sat_neg_chk:
    ld a,(PROD+3)
    cp 255
    jr nz,sat_neg
    ld a,(PROD+2)
    cp 255
    jr nz,sat_neg
    ld a,(PROD+1)
    or a
    jp p,sat_neg
    ld hl,(PROD)
    ret
sat_neg:
    ld hl,32768
    ret

matvec_bias:
    ld a,1
    ld (MV_BFLAG),a
    jr matvec_init
matvec:
    xor a
    ld (MV_BFLAG),a
matvec_init:
    ld hl,(MV_WP)
    ld (MV_WCUR),hl
    ld hl,(MV_DP)
    ld (MV_DCUR),hl
    ld hl,(MV_BP)
    ld (MV_BCUR),hl
    ld a,(MV_ROWS)
    ld (MV_RCOUNT),a
mv_row:
    ld a,(MV_BFLAG)
    or a
    jr z,mv_zero_acc
    ld hl,(MV_BCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (MV_BCUR),hl
    ld (ACC32),de
    ld a,d
    or a
    jp p,mv_bias_pos
    ld hl,65535
    ld (ACC32+2),hl
    jr mv_acc_done
mv_bias_pos:
    ld hl,0
    ld (ACC32+2),hl
    jr mv_acc_done
mv_zero_acc:
    call clear_acc32
mv_acc_done:
    ld hl,(MV_SP)
    ld (MV_SCUR),hl
    ld a,(MV_COLS)
    ld (MV_CCOUNT),a
mv_col:
    ld hl,(MV_WCUR)
    ld a,(hl)
    inc hl
    ld (MV_WCUR),hl
    ld (TMP),a
    or a
    jp p,mv_w_pos
    ld a,255
    jr mv_w_hi
mv_w_pos:
    xor a
mv_w_hi:
    ld (TMP+1),a
    ld hl,(MV_SCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (MV_SCUR),hl
    ld (SRC16),de
    call smul16
    call add_prod_to_acc32
    ld hl,MV_CCOUNT
    dec (hl)
    jp nz,mv_col
    call copy_acc_to_prod
    ld a,(MV_SHIFT)
    ld b,a
    call asr_prod_b
    call sat_prod_hl
    ex de,hl
    ld hl,(MV_DCUR)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (MV_DCUR),hl
    ld hl,MV_RCOUNT
    dec (hl)
    jp nz,mv_row
    ret

rms_norm:
    call clear_acc32
    ld hl,(RMS_XP)
    ld (RMS_XCUR),hl
    ld a,32
    ld (RMS_COUNT),a
rms_sum_loop:
    ld hl,(RMS_XCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (RMS_XCUR),hl
    ld (TMP),de
    ld b,4
rms_x_shift:
    ld hl,TMP+1
    ld a,(hl)
    rlca
    rr (hl)
    dec hl
    rr (hl)
    djnz rms_x_shift
    ld hl,(TMP)
    ld (SRC16),hl
    call smul16
    call add_prod_to_acc32
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,rms_sum_loop
    ld b,5
    call lsr_acc32_b
    ld a,(ACC32)
    ld hl,ACC32+1
    or (hl)
    inc hl
    or (hl)
    inc hl
    or (hl)
    jr nz,rms_nonzero
    ld hl,1
    ld (ACC32),hl
rms_nonzero:
    call isqrt32
    ld hl,(RMS)
    ld a,h
    or l
    jr nz,rms_have_rms
    ld hl,1
    ld (RMS),hl
rms_have_rms:
    call udiv_inv
    ld a,(INV+1)
    or a
    jp p,rms_inv_ok
    ld hl,32767
    ld (INV),hl
rms_inv_ok:
    ld hl,(RMS_XP)
    ld (RMS_XCUR),hl
    ld hl,(RMS_GP)
    ld (RMS_GCUR),hl
    ld hl,(RMS_DP)
    ld (RMS_DCUR),hl
    ld a,32
    ld (RMS_COUNT),a
rms_out_loop:
    ld hl,(RMS_XCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (RMS_XCUR),hl
    ld (TMP),de
    ld hl,(INV)
    ld (SRC16),hl
    call smul16
    ld b,15
    call asr_prod_b
    ld hl,(PROD)
    ld (TMP),hl
    ld hl,(RMS_GCUR)
    ld a,(hl)
    inc hl
    ld (RMS_GCUR),hl
    ld (SRC16),a
    or a
    jp p,rms_g_pos
    ld a,255
    jr rms_g_hi
rms_g_pos:
    xor a
rms_g_hi:
    ld (SRC16+1),a
    call smul16
    ld a,(RMS_SG)
    ld b,a
    call asr_prod_b
    call sat_prod_hl
    ex de,hl
    ld hl,(RMS_DCUR)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (RMS_DCUR),hl
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,rms_out_loop
    ret

sub_scra_from_acc_to_scrb:
    or a
    ld hl,(ACC32)
    ld de,(SCR_A)
    sbc hl,de
    ld (SCR_B),hl
    ld hl,(ACC32+2)
    ld de,(SCR_A+2)
    sbc hl,de
    ld (SCR_B+2),hl
    ret

isqrt32:
    ld hl,0
    ld (RMS),hl
    ld hl,16384
    ld (T32),hl
    ld hl,0
    ld (T32+2),hl
    ld b,8
isq_loop:
    ld hl,(RMS)
    ld de,(T32)
    add hl,de
    ld (SCR_A),hl
    ld hl,0
    ld de,(T32+2)
    adc hl,de
    ld (SCR_A+2),hl
    push bc
    call sub_scra_from_acc_to_scrb
    pop bc
    jp c,isq_less
    ld hl,(SCR_B)
    ld (ACC32),hl
    ld hl,(SCR_B+2)
    ld (ACC32+2),hl
    ld hl,(RMS)
    srl h
    rr l
    ld de,(T32)
    add hl,de
    ld (RMS),hl
    jr isq_next
isq_less:
    ld hl,(RMS)
    srl h
    rr l
    ld (RMS),hl
isq_next:
    ld hl,T32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    ld hl,T32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz isq_loop
    ret

udiv_inv:
    ld hl,0
    ld (T32),hl
    ld hl,8
    ld (T32+2),hl
    ld hl,0
    ld (INV),hl
    ld b,16
udiv_loop:
    ld hl,T32
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,INV
    rl (hl)
    inc hl
    rl (hl)
    or a
    ld hl,(T32+2)
    ld de,(RMS)
    sbc hl,de
    jr c,udiv_no_sub
    ld (T32+2),hl
    ld hl,INV
    ld a,(hl)
    or 1
    ld (hl),a
udiv_no_sub:
    djnz udiv_loop
    ret

sdiv:
    xor a
    ld (SIGN),a
    ld a,(T32+3)
    or a
    jp p,sdiv_pos
    call neg_t32
    ld a,1
    ld (SIGN),a
sdiv_pos:
    ld hl,0
    ld (SCR_A),hl
    ld (SCR_A+2),hl
    ld (SCR_B),hl
    ld (SCR_B+2),hl
    ld b,32
sdiv_loop:
    ld hl,T32
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,SCR_B
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,SCR_A
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    or a
    ld hl,(SCR_B)
    ld de,(WSUM)
    sbc hl,de
    ld (PROD),hl
    ld hl,(SCR_B+2)
    ld de,0
    sbc hl,de
    ld (PROD+2),hl
    jr c,sdiv_no_commit
    ld hl,(PROD)
    ld (SCR_B),hl
    ld hl,(PROD+2)
    ld (SCR_B+2),hl
    ld hl,SCR_A
    ld a,(hl)
    or 1
    ld (hl),a
sdiv_no_commit:
    djnz sdiv_loop
    ld a,(SIGN)
    or a
    jr z,sdiv_sat
    ld a,(SCR_B)
    ld hl,SCR_B+1
    or (hl)
    inc hl
    or (hl)
    inc hl
    or (hl)
    jr z,sdiv_no_adj
    ld hl,(SCR_A)
    inc hl
    ld (SCR_A),hl
    ld a,h
    or l
    jr nz,sdiv_no_adj
    ld hl,(SCR_A+2)
    inc hl
    ld (SCR_A+2),hl
sdiv_no_adj:
    call neg_scra
sdiv_sat:
    call copy_scra_to_prod
    call sat_prod_hl
    ld (SCR_A),hl
    ret

attn_head:
    ld hl,35840
    ld (SCORES_P),hl
    ld hl,35888
    ld (WTS_P),hl
    ld a,(HEAD_PARAM)
    call head_offset
    ld de,(KB)
    add hl,de
    ld (KROW),hl
    xor a
    ld (TIDX),a
ah_score_loop:
    call clear_t32
    xor a
    ld (JIDX),a
ah_dot_loop:
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(QP)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(KROW)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (SRC16),de
    call smul16
    call add_prod_to_t32
    ld hl,JIDX
    inc (hl)
    ld a,(JIDX)
    cp 8
    jp nz,ah_dot_loop
    call copy_t32_to_prod
    ld b,14
    call asr_prod_b
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld de,(PROD)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    ld hl,(KROW)
    ld de,64
    add hl,de
    ld (KROW),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_score_loop
    ld hl,(SCORES_P)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (MAXSF),de
    ld a,1
    ld (TIDX),a
ah_max_loop:
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp z,ah_max_done
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld a,d
    xor 128
    ld c,a
    ld a,(MAXSF+1)
    xor 128
    cp c
    jr c,ah_max_update
    jr nz,ah_max_next
    ld a,(MAXSF)
    cp e
    jr c,ah_max_update
    jr ah_max_next
ah_max_update:
    ld (MAXSF),de
ah_max_next:
    ld hl,TIDX
    inc (hl)
    jr ah_max_loop
ah_max_done:
    ld hl,0
    ld (WSUM),hl
    xor a
    ld (TIDX),a
ah_weight_loop:
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,(MAXSF)
    or a
    sbc hl,de
    ld a,h
    or a
    jr z,ah_delta_byte
    jp m,ah_delta_zero
    ld a,127
    jr ah_delta_ready
ah_delta_byte:
    ld a,l
    cp 128
    jr c,ah_delta_ready
    ld a,127
    jr ah_delta_ready
ah_delta_zero:
    xor a
ah_delta_ready:
    ld e,a
    ld d,0
    ld hl,exp_lut
    add hl,de
    ld a,(hl)
    ld c,a
    ld a,(TIDX)
    ld l,a
    ld h,0
    ld de,(WTS_P)
    add hl,de
    ld (hl),c
    ld a,c
    ld hl,(WSUM)
    ld e,a
    ld d,0
    add hl,de
    ld (WSUM),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_weight_loop
    ld hl,(WSUM)
    ld a,h
    or l
    jr nz,ah_wsum_ok
    ld hl,1
    ld (WSUM),hl
ah_wsum_ok:
    xor a
    ld (JIDX),a
ah_out_loop:
    call clear_t32
    ld a,(HEAD_PARAM)
    call head_offset
    ld de,(VB)
    add hl,de
    ld (VROW),hl
    xor a
    ld (TIDX),a
ah_v_loop:
    ld a,(TIDX)
    ld l,a
    ld h,0
    ld de,(WTS_P)
    add hl,de
    ld a,(hl)
    ld (TMP),a
    xor a
    ld (TMP+1),a
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(VROW)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (SRC16),de
    call smul16
    call add_prod_to_t32
    ld hl,(VROW)
    ld de,64
    add hl,de
    ld (VROW),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_v_loop
    call sdiv
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(OP)
    add hl,de
    ld de,(SCR_A)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    ld hl,JIDX
    inc (hl)
    ld a,(JIDX)
    cp 8
    jp nz,ah_out_loop
    ret

residual_add:
    ld a,32
    ld (RMS_COUNT),a
res_loop:
    ld hl,(RES_DST)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld hl,(RES_SRC)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,(TMP)
    add hl,de
    ex de,hl
    ld hl,(RES_DST)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (RES_DST),hl
    ld hl,(RES_SRC)
    inc hl
    inc hl
    ld (RES_SRC),hl
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,res_loop
    ret

relu:
    ld hl,(RELU_PTR)
relu_loop:
    inc hl
    ld a,(hl)
    or a
    jp p,relu_skip
    xor a
    ld (hl),a
    dec hl
    ld (hl),a
    inc hl
relu_skip:
    inc hl
    ld (RELU_PTR),hl
    ld hl,RELU_COUNT
    dec (hl)
    jp nz,relu
    ret

argmax:
    ld hl,(ARG_PTR)
    ld de,8
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld a,4
    ld (BPE_IDX),a
    ld a,5
    ld (RMS_COUNT),a
arg_loop:
    ld a,(RMS_COUNT)
    cp 128
    jr z,arg_done
    ld l,a
    ld h,0
    add hl,hl
    ld de,(ARG_PTR)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld a,d
    xor 128
    ld c,a
    ld a,(TMP+1)
    xor 128
    cp c
    jr c,arg_update
    jr nz,arg_next
    ld a,(TMP)
    cp e
    jr c,arg_update
    jr arg_next
arg_update:
    ld (TMP),de
    ld a,(RMS_COUNT)
    ld (BPE_IDX),a
arg_next:
    ld hl,RMS_COUNT
    inc (hl)
    jr arg_loop
arg_done:
    ld a,(BPE_IDX)
    ret


banner:
    db 32,32,32,47,92,32,32,32,47,92,13,10,32,32,47,32,32,92,95,47,32,32,92,13
    db 10,32,32,46,45,45,45,45,45,45,45,46,13,10,32,124,32,62,32,32,32,32,32,60
    db 32,124,13,10,32,124,32,32,32,94,94,94,32,32,32,124,13,10,32,124,46,46,124,126
    db 126,126,124,46,46,124,13,10,32,32,92,32,32,45,45,45,32,32,47,13,10,32,32,32
    db 92,95,95,95,95,95,47,13,10,13,10,13,10,13,10,77,69,32,77,65,70,85,76,13
    db 10,77,69,32,69,86,73,76,32,84,87,73,78,32,79,70,32,77,69,70,85,76,13,10
    db 13,10,83,79,85,76,32,80,76,65,89,69,82,32,67,80,67,13,10,50,48,50,54,32
    db 45,32,71,73,90,77,79,54,52,75,32,124,32,71,73,68,69,79,78,13,10,13,10,82
    db 69,65,76,32,84,82,65,78,83,70,79,82,77,69,82,46,32,82,69,65,76,32,87,69
    db 73,71,72,84,83,46,13,10,76,79,65,68,69,68,32,70,79,82,32,65,77,83,84,82
    db 65,68,32,67,80,67,46,13,10,13,10,0
ready_msg:
    db 84,89,80,69,32,65,78,68,32,73,32,87,73,76,76,32,83,67,82,69,65,77,32,65
    db 84,32,89,79,85,13,10,69,86,69,78,84,85,65,76,76,89,46,46,46,32,65,70,84
    db 69,82,32,77,73,78,85,84,69,83,33,13,10,84,89,80,69,32,39,81,39,32,84,79
    db 32,81,85,73,84,46,13,10,0
prompt_str:
    db 89,79,85,62,32,0
cpc_str:
    db 67,80,67,62,32,0
quit_msg:
    db 13,10,45,45,32,65,84,84,69,78,84,73,79,78,32,73,83,32,65,76,76,32,84,72
    db 73,83,32,78,69,69,68,69,68,13,10,71,73,90,77,79,54,52,75,13,10,0
exp_lut:
    db 255,240,225,211,199,187,175,165,155,145,136,128,120,113,106,100,94,88,83,78,73,69,64,61
    db 57,53,50,47,44,42,39,37,35,32,30,29,27,25,24,22,21,20,18,17,16,15,14,14
    db 13,12,11,11,10,9,9,8,8,7,7,6,6,6,5,5,5,4,4,4,4,3,3,3
    db 3,3,2,2,2,2,2,2,2,2,2,1,1,1,1,1,1,1,1,1,1,1,1,1
    db 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
    db 1,1,1,1,1,1,1,0
decode_offsets:
    db 0,0,1,0,2,0,3,0,4,0,6,0,8,0,10,0,12,0,14,0,16,0,18,0
    db 20,0,22,0,24,0,26,0,28,0,30,0,32,0,34,0,36,0,38,0,40,0,42,0
    db 44,0,46,0,48,0,50,0,52,0,54,0,56,0,58,0,60,0,62,0,64,0,66,0
    db 68,0,70,0,72,0,74,0,77,0,81,0,84,0,87,0,90,0,93,0,96,0,99,0
    db 102,0,106,0,109,0,112,0,115,0,118,0,121,0,124,0,127,0,130,0,133,0,136,0
    db 139,0,142,0,146,0,149,0,154,0,157,0,160,0,163,0,166,0,169,0,174,0,177,0
    db 181,0,185,0,189,0,192,0,197,0,202,0,205,0,208,0,211,0,216,0,221,0,224,0
    db 227,0,230,0,235,0,240,0,243,0,246,0,249,0,252,0,0,1,5,1,10,1,14,1
    db 17,1,20,1,25,1,28,1,31,1,34,1,38,1,43,1,47,1,50,1,54,1,57,1
    db 61,1,65,1,70,1,74,1,77,1,82,1,89,1,93,1,96,1,100,1,103,1,106,1
    db 112,1,116,1,121,1,124,1,130,1,133,1,136,1,141,1
decode_strings:
    db 0,0,0,0,32,0,97,0,98,0,99,0,100,0,101,0,102,0,103,0,104,0,105,0
    db 106,0,107,0,108,0,109,0,110,0,111,0,112,0,113,0,114,0,115,0,116,0,117,0
    db 118,0,119,0,120,0,121,0,122,0,46,0,39,0,33,0,63,0,44,0,59,0,58,0
    db 45,0,111,117,0,121,111,117,0,114,101,0,116,104,0,105,110,0,105,39,0,97,116,0
    db 105,115,0,101,114,0,105,110,103,0,104,101,0,111,110,0,109,101,0,118,101,0,101,101
    db 0,116,111,0,97,110,0,108,111,0,101,115,0,97,108,0,111,114,0,97,121,0,97,114
    db 101,0,115,116,0,116,104,97,116,0,104,97,0,98,101,0,109,97,0,102,117,0,105,116
    db 0,121,111,117,39,0,103,111,0,102,117,108,0,116,104,101,0,102,101,101,0,97,114,0
    db 104,101,114,101,0,102,101,101,108,0,109,121,0,101,110,0,115,111,0,108,111,118,101,0
    db 121,111,117,33,0,107,101,0,114,105,0,108,105,0,121,111,117,114,0,116,104,105,115,0
    db 111,100,0,116,105,0,110,111,0,112,112,0,104,97,116,0,104,97,112,112,0,119,104,97
    db 116,0,119,111,110,0,103,104,0,101,100,0,103,111,111,100,0,101,108,0,100,111,0,108
    db 100,0,119,97,121,0,102,117,108,33,0,100,101,114,0,104,111,0,118,101,114,0,121,33
    db 0,116,101,114,0,102,111,114,0,121,111,117,46,0,116,111,111,0,97,117,0,99,97,114
    db 101,0,119,111,110,100,101,114,0,119,111,114,0,108,101,0,97,108,108,0,116,97,0,111
    db 107,0,116,104,105,110,103,0,107,101,115,0,104,101,97,114,0,101,33,0,104,101,114,101
    db 46,0,115,33,0,99,111,0,108,105,107,101,0,111,110,101,0
merge_table:
    db 19,25,39,29,39,40,22,9,41,24,12,42,13,18,43,13,32,44,5,24,45,13,23,46
    db 9,22,47,43,11,48,12,9,49,19,18,50,17,9,51,26,9,52,9,9,53,24,19,54
    db 5,18,55,16,19,56,9,23,57,5,16,58,19,22,59,5,29,60,5,41,61,23,24,62
    db 42,45,63,12,5,64,6,9,65,17,5,66,10,25,67,13,24,68,40,32,69,11,19,70
    db 67,16,71,42,9,72,10,53,73,5,22,74,49,41,75,73,16,76,17,29,77,9,18,78
    db 23,19,79,56,52,80,40,33,81,15,9,82,22,13,83,16,13,84,40,22,85,42,46,86
    db 19,8,87,24,13,88,18,19,89,20,20,90,12,45,91,64,90,92,27,91,93,27,50,94
    db 11,12,95,9,8,96,70,87,97,9,16,98,8,19,99,16,8,100,27,60,101,71,33,102
    db 8,47,103,12,19,104,26,47,105,29,33,106,24,47,107,10,59,108,40,31,109,54,19,110
    db 5,25,111,7,61,112,94,103,113,27,59,114,16,9,115,58,16,116,24,5,117,19,15,118
    db 42,48,119,15,57,120,49,74,121,9,33,122,75,31,123,23,33,124,7,19,125,84,82,126
    db 50,9,127,255
CONST_XN:
    dw 35920
vars_start:
POS: db 0
HEAD: db 0
HEAD_PARAM: db 0
CUR_H: dw 0
CUR_D: dw 0
EMB_TP: dw 0
EMB_PP: dw 0
EMB_DP: dw 0
EMB_SH1: db 0
EMB_SH2: db 0
MV_WP: dw 0
MV_SP: dw 0
MV_DP: dw 0
MV_BP: dw 0
MV_ROWS: db 0
MV_COLS: db 0
MV_SHIFT: db 0
MV_BFLAG: db 0
MV_WCUR: dw 0
MV_SCUR: dw 0
MV_DCUR: dw 0
MV_BCUR: dw 0
MV_RCOUNT: db 0
MV_CCOUNT: db 0
RMS_XP: dw 0
RMS_GP: dw 0
RMS_DP: dw 0
RMS_SG: db 0
RMS_XCUR: dw 0
RMS_GCUR: dw 0
RMS_DCUR: dw 0
RMS_COUNT: db 0
QP: dw 0
KB: dw 0
VB: dw 0
OP: dw 0
NKEYS: db 0
SCORES_P: dw 0
WTS_P: dw 0
KROW: dw 0
VROW: dw 0
TIDX: db 0
JIDX: db 0
MAXSF: dw 0
WSUM: dw 0
RES_DST: dw 0
RES_SRC: dw 0
RELU_PTR: dw 0
RELU_COUNT: db 0
ARG_PTR: dw 0
BPE_A: db 0
BPE_B: db 0
BPE_M: db 0
BPE_PTR: dw 0
BPE_IDX: db 0
BPE_SHIFT: db 0
ACC32: ds 4
T32: ds 4
SCR_A: ds 4
SCR_B: ds 4
PROD: ds 4
TMP: dw 0
SRC16: dw 0
SIGN: db 0
RMS: dw 0
INV: dw 0
vars_end: